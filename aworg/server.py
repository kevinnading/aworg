"""The owner interface's backing service.

Everything the owner interface can do goes through here. The Resident is not
exposed directly; the API is the controlled surface in front of it, which is
the shape the Resident API will eventually need when generated applications
are allowed to talk to a Resident under far tighter restrictions.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from contextlib import asynccontextmanager
import re
import secrets as secrets_module
import shutil
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .models import CAPABILITY_TAGS, PROVIDER_LABELS, ModelError, build_adapter
from .paths import Paths
from .journal import Journal
from . import journal as journal_module
from . import personas as personas_module
from .resident import Busy, Resident
from .secrets import SecretStore, credential_ref
from . import layout as layout_settings
from . import lifecycle, panes, providers
from .storage import Store
from .theme import (
    PRESETS,
    TOKEN_GROUPS,
    describe,
    declarations,
    resolve,
    sanitize_overrides,
)


WEB_DIR = Path(__file__).parent / "web"

#: What a persona's image assets are served as. A short table rather than
#: mimetypes.guess_type, because the set of things a persona may carry is
#: deliberately short and guessing would widen it.
MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
}


#: Table names as an owner would say them. A reset entry reading "4 journal,
#: 1 capability_state" is the schema leaking into the one record of the
#: largest thing that can happen to an Aworg.
RESET_NAMES = {
    "messages": "messages",
    "conversations": "conversations",
    "tasks": "tasks",
    "workers": "workers",
    "capability_state": "capability settings",
    "journal": "Living Log entries",
    "connections": "model connections",
}


def _reset_detail(
    removed: dict[str, int], stopped: int, saved: list[str]
) -> str:
    """What a reset actually took, in a sentence.

    Assembled rather than formatted inline because the two facts are
    independent: what was erased, and whether it can be got back. An earlier
    version joined them with a conditional that swallowed the counts whenever
    there was no backup -- which is exactly the case where knowing what went
    matters most.
    """
    gone = ", ".join(
        f"{count} {RESET_NAMES.get(table, table)}"
        for table, count in removed.items()
        if count
    )
    parts = [f"Erased {gone}." if gone else "There was nothing to erase."]
    if stopped:
        parts.append(
            f"{stopped} running program(s) were stopped."
        )
    parts.append(
        f"The databases were copied to backups/ first, as {', '.join(saved)}."
        if saved else
        "Nothing was backed up -- there was no database to copy."
    )
    return " ".join(parts)


class ConnectionBody(BaseModel):
    name: str
    provider: str
    model: str
    base_url: str | None = None
    tags: list[str] = []
    reasoning: str = "auto"
    context: int | None = None
    enabled: bool = True
    credential: str | None = None
    tokens_per_minute: int | None = None


class ModelsBody(BaseModel):
    provider: str
    base_url: str | None = None
    #: Typed into the form and used once; never stored by this endpoint.
    credential: str | None = None
    #: For refreshing the list on a connection that already has a key.
    connection_id: str | None = None


class ConnectionPatch(BaseModel):
    name: str | None = None
    provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    tags: list[str] | None = None
    reasoning: str | None = None
    #: The window in tokens. 0 clears it back to unknown.
    context: int | None = None
    enabled: bool | None = None
    credential: str | None = None
    #: 0 clears it back to no limit.
    tokens_per_minute: int | None = None


class ResidentPatch(BaseModel):
    primary_connection_id: str | None = None
    worker_connection_id: str | None = None
    system_prompt: str | None = None


class ChatBody(BaseModel):
    message: str


class AppearancePatch(BaseModel):
    preset: str | None = None
    overrides: dict[str, str] | None = None


class CapabilityPatch(BaseModel):
    enabled: bool


class ResetBody(BaseModel):
    confirm: str
    #: Defaults to keeping them, because the alternative is an owner who
    #: wanted a clean conversation and finds their Resident mute with no
    #: model to think with.
    keep_connections: bool = True


class TaskPatch(BaseModel):
    title: str | None = None
    detail: str | None = None
    state: str | None = None
    note: str | None = None
    position: int | None = None


class WorkerBody(BaseModel):
    name: str
    description: str = ""
    connection_id: str | None = None
    system_prompt: str = ""
    #: Tool names, capability ids, or both. Empty means no tools at all --
    #: deliberately not "all of them", because a worker's scope is the thing
    #: that makes it safe to hand work to.
    tools: list[str] = []
    #: Skill names this worker is given in full. Scoped like tools; unlike
    #: the Resident's, these are put in front of it rather than offered.
    skills: list[str] = []
    enabled: bool = True


class WorkerPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    connection_id: str | None = None
    system_prompt: str | None = None
    tools: list[str] | None = None
    skills: list[str] | None = None
    enabled: bool | None = None


class ReportBody(BaseModel):
    """What a running application says happened to it.

    Four fields, matching what the MVP spec asks an application to be able to
    say: what failed, how badly, where, and whatever surrounds it. Kept as
    separate fields rather than one message so that what reads this back can
    reason about it instead of parsing prose.
    """
    summary: str
    #: The application's own word for how bad it is -- `error`, `warning`,
    #: `critical`. Mapped onto AWORG's three levels; see journal.FROM_APPLICATION.
    severity: str = "error"
    #: Where it happened. A route, a file, a job name -- whatever the
    #: application knows itself by.
    where: str = ""
    detail: str = ""
    #: Which application, for an Aworg running more than one.
    application: str = ""


class ResolveBody(BaseModel):
    #: What was done about it. Required in spirit rather than by the schema:
    #: an entry closed with no account of why is one that teaches nothing.
    resolution: str = ""
    by: str = "owner"


class PersonaBody(BaseModel):
    #: The persona to wear. Empty or null means the shipped default, which
    #: is how "I have not chosen" is expressed -- see personas.DEFAULT_PERSONA.
    name: str | None = None


class LayoutPatch(BaseModel):
    #: The whole set of dragged sizes. An empty object resets the view.
    #:
    #: Deliberately untyped past "an object". Declaring int here would make
    #: pydantic refuse the entire request over one bad value, which is the
    #: opposite of what is wanted: one stale or malformed pane should be
    #: dropped, not take a good layout down with it. layout.sanitize is the
    #: single gate, and it is strict.
    sizes: dict[str, Any]


def create_app(paths: Paths, address: str = "http://127.0.0.1:8420") -> FastAPI:
    paths.ensure()
    store = Store(paths.state_db)
    secrets = SecretStore(paths.secrets_db)
    resident = Resident(store, secrets, paths)
    # Where an application AWORG starts should send what happens to it. Told
    # rather than discovered: a server has no way of knowing what address
    # anyone reached it on, and guessing would hand out a URL that works on
    # the developer's machine and nowhere else.
    resident.reporting = {
        journal_module.URL_VAR: f"{address.rstrip('/')}/api/log",
        journal_module.TOKEN_VAR: "",
    }

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        """Take the Resident's running programs down with the Aworg.

        A process table lives in this process, so an Aworg that exits without
        stopping what it started leaves servers running that the next Aworg
        cannot see, adopt, or stop -- it can only spawn its own. That is how a
        python -m http.server survived ten hours and several restarts, still
        holding port 8000 against every attempt to bind it.

        Stopping them on the way out is the honest half of the bargain: AWORG
        will not claim a process it did not start, so it must not abandon one
        it did.

        This is also where the Living Log's follower runs. It has to be
        started against a running loop and stopped with the app, and doing it
        here means an Aworg cannot end up serving pages with nothing reading
        the Activity stream -- which would leave the pane looking calm rather
        than deaf.
        """
        # Made now rather than on first use, so that the very first
        # application the Resident starts already has it in its environment.
        resident.reporting[journal_module.TOKEN_VAR] = report_token()
        follower = asyncio.create_task(resident.journal.follow(resident.activities))
        # Reads the Living Log on a schedule. Started here for the same
        # reason the follower is: it needs a running loop and it should stop
        # with the app, and an Aworg serving pages with nothing watching its
        # log would look calm rather than blind.
        watcher = asyncio.create_task(resident.watch.run())
        resident.journal.record(
            "AWORG started",
            kind="aworg",
            detail=host_started_detail(),
        )
        yield
        follower.cancel()
        watcher.cancel()
        for task in (follower, watcher):
            with contextlib.suppress(asyncio.CancelledError):
                await task
        # Recorded before the processes go, so the count is what was actually
        # running rather than zero.
        running = sum(1 for p in resident.processes.all() if p.alive)
        resident.journal.record(
            "AWORG stopped",
            kind="aworg",
            detail=(
                f"{running} running program(s) were stopped with it."
                if running else ""
            ),
        )
        await resident.processes.stop_all()

    def host_started_detail() -> str:
        """One line about what this Aworg woke up as.

        The Living Log's first entry after a restart should say enough that
        the gap in the log is explained -- an owner reading back through the
        night wants to know the Aworg went away and came back, and on what.
        """
        facts = resident.host or {}
        machine = " ".join(
            part for part in (facts.get("os"), facts.get("release")) if part
        ) or "this machine"
        connection = resident.primary_connection()
        model = (connection or {}).get("model") or "no model connected"
        return f"On {machine}, with {model}."

    app = FastAPI(title="AWORG", version="0.1.0", lifespan=lifespan)

    def present(connection: dict[str, Any]) -> dict[str, Any]:
        """Shape a connection for the owner interface.

        Credentials are never returned once stored -- only whether one exists.
        """
        return {
            **connection,
            "has_credential": secrets.has(credential_ref(connection["id"])),
        }

    # -- what the interface needs to orient itself ----------------------

    @app.get("/api/meta")
    def meta() -> dict[str, Any]:
        return {
            "providers": PROVIDER_LABELS,
            # The full profiles, so the form can pre-fill a base URL, know
            # whether to ask for a credential, and say what is known about
            # tool support -- without the browser holding its own copy of a
            # table that lives in providers.py.
            "provider_profiles": providers.for_interface(),
            "capability_tags": CAPABILITY_TAGS,
            "home": str(paths.home),
        }

    @app.get("/api/host")
    def host_facts() -> dict[str, Any]:
        """What AWORG observed about this machine when it started."""
        return resident.host

    @app.get("/api/state")
    def state() -> dict[str, Any]:
        config = store.get_resident()
        return {
            "resident": resident.state(),
            "primary_connection_id": config["primary_connection_id"],
            "worker_connection_id": config["worker_connection_id"],
            "system_prompt": config["system_prompt"],
            # Here rather than in /api/meta, which is read once at boot. The
            # Resident can rename the project mid-conversation, and a header
            # that only catches up on reload would be showing the owner a
            # name their Resident has already stopped using.
            "project": store.get_project(),
        }

    # -- the Model Pool -------------------------------------------------

    @app.get("/api/connections")
    def list_connections() -> list[dict[str, Any]]:
        return [present(c) for c in store.list_connections()]

    @app.post("/api/connections")
    def create_connection(body: ConnectionBody) -> dict[str, Any]:
        connection = store.create_connection(
            name=body.name.strip() or "Untitled",
            provider=body.provider,
            model=body.model.strip(),
            base_url=(body.base_url or "").strip() or None,
            tags=body.tags,
            reasoning=body.reasoning,
            context=body.context or None,
            enabled=body.enabled,
        )
        if body.credential:
            secrets.set(credential_ref(connection["id"]), body.credential)

        # A first connection becomes the Resident's mind automatically. Making
        # the owner perform a separate step here would be ceremony, not choice.
        if store.get_resident()["primary_connection_id"] is None:
            store.update_resident(primary_connection_id=connection["id"])

        return present(connection)

    @app.patch("/api/connections/{connection_id}")
    def update_connection(connection_id: str, body: ConnectionPatch) -> dict[str, Any]:
        if store.get_connection(connection_id) is None:
            raise HTTPException(404, "No such connection")
        connection = store.update_connection(
            connection_id,
            name=body.name,
            provider=body.provider,
            model=body.model,
            base_url=body.base_url,
            tags=body.tags,
            reasoning=body.reasoning,
            context=body.context,
            tokens_per_minute=body.tokens_per_minute,
            enabled=body.enabled,
        )
        # An empty string means "leave the stored credential alone", so that
        # editing a connection never silently discards its credential.
        if body.credential:
            secrets.set(credential_ref(connection_id), body.credential)
        return present(connection)  # type: ignore[arg-type]

    @app.delete("/api/connections/{connection_id}")
    def delete_connection(connection_id: str) -> dict[str, str]:
        if store.get_connection(connection_id) is None:
            raise HTTPException(404, "No such connection")
        store.delete_connection(connection_id)
        secrets.delete(credential_ref(connection_id))
        return {"status": "deleted"}

    @app.post("/api/connections/{connection_id}/test")
    async def test_connection(connection_id: str) -> dict[str, Any]:
        connection = store.get_connection(connection_id)
        if connection is None:
            raise HTTPException(404, "No such connection")
        api_key = secrets.get(credential_ref(connection_id))
        if not api_key:
            return {"ok": False, "detail": "No credential stored for this connection."}
        adapter = build_adapter(connection, api_key)
        try:
            await adapter.probe()
        except ModelError as exc:
            return {"ok": False, "detail": str(exc)}

        # While we have the server's attention, ask how big its window is.
        # A local server will say; that answer is recorded if the owner has
        # not set one themselves, so the ceiling fills itself in for the
        # models that can announce it and stays the owner's to type for the
        # ones that cannot.
        detected = await adapter.detect_context()
        chosen = connection.get("context")
        if detected and not chosen:
            store.update_connection(connection_id, context=detected)
            note = f" Context window: {detected:,} tokens (reported by the server)."
        elif detected and chosen and detected != chosen:
            # The owner's number wins -- they may know something the server
            # does not -- but a disagreement is worth a sentence, not silence.
            note = (f" Context window set to {chosen:,} tokens;"
                    f" the server reports {detected:,}.")
        elif chosen:
            note = f" Context window: {chosen:,} tokens."
        else:
            note = " Context window unknown - set it in the connection if you know it."
        return {"ok": True, "detail": "Reached the model successfully." + note}

    @app.post("/api/models")
    async def list_models(body: ModelsBody) -> dict[str, Any]:
        """What a provider will serve, asked before anything is saved.

        Takes the form's current values rather than a connection id, because
        the owner is choosing a model in order to create the connection --
        requiring it to exist first would mean saving something broken to
        find out what to put in it.

        A credential typed into the form is used and not stored. When the
        field is left blank on an existing connection -- which is what an
        owner does when they are not changing the key -- the stored one is
        used instead, so refreshing the list does not mean retyping a secret.
        """
        profile = providers.profile(body.provider)
        api_key = body.credential or ""
        if not api_key and body.connection_id:
            api_key = secrets.get(credential_ref(body.connection_id)) or ""
        if not api_key and profile["auth"] != "none":
            return {"ok": False, "detail": "A credential is needed to ask for the list.",
                    "models": []}

        adapter = build_adapter(
            {
                "provider": body.provider,
                "model": "",
                "base_url": (body.base_url or "").strip() or None,
            },
            api_key,
        )
        try:
            found = await adapter.list_models()
        except ModelError as exc:
            return {"ok": False, "detail": str(exc), "models": []}
        if not found:
            return {
                "ok": False,
                "detail": "That provider did not publish a model list. Type the name instead.",
                "models": [],
            }
        return {"ok": True, "detail": f"{len(found)} models.", "models": found}

    # -- the Resident ---------------------------------------------------

    @app.patch("/api/resident")
    def update_resident(body: ResidentPatch) -> dict[str, Any]:
        fields: dict[str, Any] = {}
        if body.primary_connection_id is not None:
            if store.get_connection(body.primary_connection_id) is None:
                raise HTTPException(404, "No such connection")
            fields["primary_connection_id"] = body.primary_connection_id
        if body.worker_connection_id is not None:
            # An empty string clears the assignment; workers then fall back to
            # whatever the Resident itself is using.
            if body.worker_connection_id == "":
                fields["worker_connection_id"] = None
            elif store.get_connection(body.worker_connection_id) is None:
                raise HTTPException(404, "No such connection")
            else:
                fields["worker_connection_id"] = body.worker_connection_id
        if body.system_prompt is not None:
            fields["system_prompt"] = body.system_prompt
        if fields:
            store.update_resident(**fields)
        return {"resident": resident.state(), **store.get_resident()}

    @app.get("/api/conversation")
    def conversation() -> dict[str, Any]:
        return resident.conversation()

    @app.get("/api/context")
    async def context_usage() -> dict[str, Any]:
        """How much of the model's window the next turn will use."""
        return await resident.context_usage()

    def _follow(turn) -> StreamingResponse:
        async def events():
            async for event in resident.follow(turn):
                yield json.dumps(event) + "\n"

        return StreamingResponse(events(), media_type="application/x-ndjson")

    @app.post("/api/chat")
    async def chat(body: ChatBody) -> StreamingResponse:
        text = body.message.strip()
        if not text:
            raise HTTPException(400, "Empty message")
        try:
            turn = resident.start_turn(text)
        except Busy as exc:
            raise HTTPException(409, str(exc)) from exc
        return _follow(turn)

    @app.get("/api/chat/stream")
    async def resume_chat() -> StreamingResponse:
        """Rejoin a reply already in progress.

        What makes a refresh survivable: the turn is server-side, so this
        replays everything said so far and then follows it live.
        """
        turn = resident.turn
        if turn is None or turn.done:
            raise HTTPException(404, "Nothing in progress")
        return _follow(turn)

    @app.get("/api/chat/active")
    def chat_active() -> dict[str, Any]:
        turn = resident.turn
        return {"active": bool(turn and not turn.done)}

    @app.post("/api/chat/stop")
    def stop_chat() -> dict[str, Any]:
        """Stop the reply in progress. Whatever it said is kept."""
        return {"stopped": resident.stop_turn()}

    # -- appearance -----------------------------------------------------

    def appearance_payload() -> dict[str, Any]:
        stored = store.get_appearance()
        return {
            "preset": stored["preset"],
            "overrides": stored["overrides"],
            "colors": resolve(stored["preset"], stored["overrides"]),
            "presets": describe(),
            "groups": [
                {
                    "id": group["id"],
                    "label": group["label"],
                    "hint": group["hint"],
                    "tokens": [
                        {"name": name, "label": label} for name, label in group["tokens"]
                    ],
                }
                for group in TOKEN_GROUPS
            ],
        }

    @app.get("/api/appearance")
    def get_appearance() -> dict[str, Any]:
        return appearance_payload()

    @app.patch("/api/appearance")
    def update_appearance(body: AppearancePatch) -> dict[str, Any]:
        fields: dict[str, Any] = {}
        if body.preset is not None:
            if body.preset not in PRESETS:
                raise HTTPException(404, "No such preset")
            fields["preset"] = body.preset
        if body.overrides is not None:
            # Whatever the interface sends, only known tokens holding real hex
            # colours are kept. This is the last point before these values
            # become a stylesheet, so it is the point that has to be strict.
            fields["overrides"] = sanitize_overrides(body.overrides)
        if fields:
            store.update_appearance(**fields)
        return appearance_payload()

    # -- layout ---------------------------------------------------------

    def layout_payload() -> dict[str, Any]:
        sizes = layout_settings.resolve(store.get_layout())
        return {
            "sizes": sizes,
            "panes": layout_settings.describe(),
            "is_default": layout_settings.is_default(sizes),
        }

    @app.get("/api/layout")
    def get_layout() -> dict[str, Any]:
        return layout_payload()

    @app.patch("/api/layout")
    def update_layout(body: LayoutPatch) -> dict[str, Any]:
        # Sizes are clamped here as well as in the browser. The browser stops a
        # drag at the boundary out of courtesy; this is the copy that has to
        # hold, because it is the one that becomes a CSS length.
        store.update_layout(layout_settings.sanitize(body.sizes))
        return layout_payload()

    # -- how the interface is set up, as a stylesheet ---------------------

    @app.get("/api/interface.css")
    def interface_css() -> Response:
        """The owner's colours and proportions, loaded before the first paint.

        A blocking stylesheet rather than values applied by script on load:
        the owner should never watch the interface appear in the default
        scheme, at the default sizes, and then correct itself into theirs.

        Colour and layout ride together because they arrive together. Two
        stylesheets would mean two chances to paint half-configured.
        """
        appearance = store.get_appearance()
        colors = declarations(resolve(appearance["preset"], appearance["overrides"]))
        sizes = layout_settings.to_css(layout_settings.resolve(store.get_layout()))
        # The persona's own room, and only its own room.
        #
        # Scoped to the chat rather than joining the tokens above, because the
        # owner chose the interface's colours and a persona is a guest in
        # them. It rides in the same stylesheet for the same reason colour and
        # layout do -- they arrive together, and a second request would be a
        # second chance to paint the interface without the Resident in it.
        room = resident.personas.css(store.get_resident().get("persona"))
        return Response(
            content=":root {\n" + colors + sizes + "}\n" + room,
            media_type="text/css",
            # Both change the moment the owner drags or picks, and a cached
            # copy would outlive the choice.
            headers={"Cache-Control": "no-store"},
        )

    # -- the status column ------------------------------------------------

    def workspace_has_files() -> bool:
        try:
            return any(paths.workspace.iterdir())
        except OSError:
            return False

    @app.get("/api/lifecycle")
    def app_lifecycle() -> dict[str, Any]:
        """Where the Resident's application is in its life.

        Assessed from what is observably true rather than from anything the
        Resident reports, because an owner who could audit the Resident's
        claims would not need AWORG in the first place.
        """
        serving = serving_now()
        return lifecycle.assess(
            workspace_has_files(), serving, answered_now(serving), watching_now()
        )

    def watching_now() -> dict[str, Any] | None:
        """Whether the Living Log is connected and actually being read.

        Both halves, and neither is enough alone. An endpoint nobody has
        posted to is a promise rather than a channel, and a watcher that has
        been started but has never completed a pass has inspected nothing.
        This stage tells an owner their application can say it is in trouble
        and that something is listening, so it should not say so until both
        are observably true.
        """
        reporters = store.journal_reporters()
        looked = resident.watch.snapshot()
        if not reporters or not looked["passes"]:
            return None
        return {
            "application": reporters[0] if len(reporters) == 1
                           else f"{len(reporters)} applications",
            "passes": looked["passes"],
            "outstanding": looked["outstanding"],
        }

    @app.get("/api/panes")
    def status_panes() -> list[dict[str, Any]]:
        """Every pane in the status column, and what it currently holds.

        One request rather than seven. These are read together, and they
        stay together until one of them grows enough to want its own.
        """
        return panes.describe(
            resident.host,
            resident.registry,
            store.capability_enabled,
            store.list_workers(),
            store.list_tasks(store.OPEN_STATES),
            [
                {
                    **s.snapshot(),
                    "enabled": store.skill_enabled(s.name),
                    "offered": s in resident.skills.offered(),
                }
                for s in resident.skills.all()
            ],
            resident.journal.entries(limit=100),
            workspace=paths.workspace,
        )

    @app.post("/api/capabilities/{capability_id}")
    def set_capability(capability_id: str, body: CapabilityPatch) -> dict[str, Any]:
        """Switch a Capability on or off.

        The owner's decision, and it outranks anything the Resident asks
        for: a disabled Capability is invisible to the Resident and to any
        worker it spawns, whatever tool scope that worker was given.

        Takes effect on the next tool call rather than the next restart,
        because the registry asks the store on every use.
        """
        if resident.registry.get_capability(capability_id) is None:
            raise HTTPException(404, f"No capability called {capability_id!r}")
        store.set_capability_enabled(capability_id, body.enabled)
        # An owner decision that changes what the Resident can do. Worth
        # keeping precisely because it is invisible afterwards: a Resident
        # that cannot run commands behaves like one that will not, and the
        # log is where the difference is written down.
        capability = resident.registry.get_capability(capability_id)
        resident.journal.record(
            f"{getattr(capability, 'label', None) or capability_id} was "
            f"{'enabled' if body.enabled else 'disabled'}",
            kind="capability",
            source="owner",
            detail=(
                "" if body.enabled else
                "Its tools are no longer offered to the Resident or to any "
                "worker, whatever tool scope that worker was given."
            ),
        )
        return {"id": capability_id, "enabled": body.enabled}

    # -- reset ----------------------------------------------------------

    #: The code the owner must type, and the only copy of it. Issued per
    #: dialog and thrown away on use, so it cannot become muscle memory --
    #: which is the entire reason for asking. A fixed word like "DELETE" is
    #: typed without reading by the third time.
    pending_code: dict[str, str] = {}

    @app.get("/api/reset/preview")
    def reset_preview() -> dict[str, Any]:
        """What a reset would erase, counted, plus a fresh confirmation code.

        Counted rather than described. "Your conversation" is easy to agree
        to; "47 messages" is the thing the owner actually has to weigh, and
        they deserve the real number before they type anything.
        """
        code = secrets_module.token_hex(3).upper()
        pending_code["code"] = code

        counts = store.task_counts()
        conversation = store.messages(store.current_conversation_id())
        workspace = paths.workspace
        files = sum(1 for _ in workspace.rglob("*")) if workspace.exists() else 0

        return {
            "code": code,
            "erases": [
                {"what": "Messages in the conversation", "count": len(conversation)},
                {"what": "Tasks in the plan", "count": sum(counts.values())},
                {"what": "Files in the Living Workspace", "count": files},
                {"what": "Workers", "count": len(store.list_workers())},
                {
                    "what": "Living Log entries",
                    "count": len(store.list_journal(limit=Journal.KEEP)),
                },
                {"what": "Model connections", "count": len(store.list_connections())},
                {
                    "what": "Running programs (servers and the like)",
                    "count": sum(1 for p in resident.processes.all() if p.alive),
                },
            ],
        }

    @app.post("/api/reset")
    async def reset_aworg(body: ResetBody) -> dict[str, Any]:
        """Put this Aworg back the way it arrived.

        The databases are copied to backups/ before anything is touched. A
        reset the owner regrets is then a file copy away from being undone,
        which is cheap to provide and impossible to add afterwards.
        """
        expected = pending_code.get("code")
        if not expected or body.confirm.strip().upper() != expected:
            raise HTTPException(400, "That confirmation code does not match.")
        # Spent, whether or not the rest succeeds. A code that survives its
        # use is a code a second click could reuse.
        pending_code.pop("code", None)

        stamp = time.strftime("%Y%m%d-%H%M%S")
        backups = paths.home / "backups"
        backups.mkdir(exist_ok=True)
        saved = []
        for name in ("state.db", "secrets.db"):
            source = paths.home / name
            if source.exists():
                target = backups / f"{source.stem}-{stamp}.db"
                shutil.copy2(source, target)
                saved.append(target.name)

        removed = store.factory_reset(keep_connections=body.keep_connections)
        if not body.keep_connections:
            secrets.clear()

        for folder in (paths.workspace, paths.logs):
            if folder.exists():
                for item in folder.iterdir():
                    shutil.rmtree(item, ignore_errors=True) if item.is_dir() else item.unlink()
            folder.mkdir(exist_ok=True)

        # Runtime state is not in the database and has to be dropped by
        # hand -- including, and this was missed, the programs the Resident
        # started. A factory reset that leaves a web server running is not a
        # factory reset: the preview kept showing a page from a server the
        # Aworg no longer knew it owned.
        stopped = await resident.processes.clear()
        # Cleared, not replaced. A new manager would leave the Living Log's
        # follower subscribed to the old one, and an Aworg that had been
        # reset would stop recording anything at all -- see forget_all.
        resident.activities.forget_all()
        # And the watch looks again, because what it is holding was erased a
        # moment ago. Without this it goes on reporting trouble from entries
        # that no longer exist -- observed doing exactly that, three
        # outstanding items in a log with none.
        resident.turn = None
        await resident.watch.inspect()

        # Written after the wipe, not before, so it survives it. A reset is
        # the largest thing that can happen to an Aworg and a Living Log that
        # came back from one with no explanation for the silence above it
        # would be the pane failing at its only job.
        resident.journal.record(
            "This Aworg was reset",
            kind="aworg",
            source="owner",
            detail=_reset_detail(removed, stopped, saved),
        )

        return {
            "status": "reset",
            "backups": saved,
            "removed": removed,
            "processes_stopped": stopped,
        }

    # -- personas ---------------------------------------------------------

    @app.get("/api/personas")
    def list_personas() -> dict[str, Any]:
        """Who this Resident could be, and who it currently is."""
        # Re-read every request, like skills: a persona is a folder, and an
        # owner who drops one in should see it without restarting anything.
        resident.personas.discover()
        active = resident.personas.active(store.get_resident().get("persona"))
        return {
            "personas": [p.snapshot() for p in resident.personas.all()],
            "active": active.name if active else None,
            "broken": resident.personas.broken,
        }

    @app.post("/api/personas")
    def set_persona(body: PersonaBody) -> dict[str, Any]:
        """Wear a different persona.

        **This does not make a new Resident.** Nothing is cleared: the
        conversation, the plan, the Living Log, the workers, the tool
        permissions and every credential are exactly where they were a moment
        ago. Only the voice changes, and the room it speaks in.

        That is the whole reason this is one column on the resident row
        rather than an operation with steps. An implementation that had to
        remember to preserve things would eventually forget one.
        """
        resident.personas.discover()
        name = (body.name or "").strip()
        if name and resident.personas.get(name) is None:
            raise HTTPException(404, f"No persona called {name!r}")
        store.update_resident(persona=name or None)
        active = resident.personas.active(name)
        resident.journal.record(
            f"Persona changed to {active.name}" if active else "Persona cleared",
            kind="persona",
            source="owner",
            detail=(
                "Voice and appearance only. The conversation, plan, memory "
                "and permissions are unchanged."
            ),
        )
        return {"active": active.name if active else None}

    @app.get("/api/personas/{name}/{asset}")
    def persona_asset(name: str, asset: str) -> Response:
        """An avatar or background, served from the persona's own folder.

        The path is resolved and then checked to be inside that folder rather
        than trusted, because theme.json arrives with the package and these
        are meant to be downloaded from strangers. See Persona.asset.
        """
        kinds = {"avatar": personas_module.AVATAR,
                 "background": personas_module.BACKGROUND}
        if asset not in kinds:
            raise HTTPException(404, "No such asset")
        persona = resident.personas.get(name)
        if persona is None:
            raise HTTPException(404, f"No persona called {name!r}")
        path = persona.asset(kinds[asset])
        if path is None:
            raise HTTPException(404, "This persona has no such asset")
        return Response(
            content=path.read_bytes(),
            media_type=MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream"),
            # Personas are edited in place, and a cached avatar would outlive
            # the edit. They are small; the request is cheap.
            headers={"Cache-Control": "no-store"},
        )

    # -- the Living Log -------------------------------------------------

    @app.get("/api/journal")
    def living_log(limit: int = 100) -> dict[str, Any]:
        """What happened, and mattered.

        Read whole rather than streamed. The Living Log is short by design and
        changes rarely; an owner opening it wants the last hundred lines, not
        a socket. Activities is the pane with a stream, because that is the
        pane about now.
        """
        return {"entries": resident.journal.entries(limit=limit)}

    @app.get("/api/watch")
    def watch_state() -> dict[str, Any]:
        """What the periodic inspection has seen.

        Runtime state, so it is read rather than stored: "when did you last
        look" has no meaning across a restart, and an Aworg that has just
        started has not looked yet however long its log is.
        """
        return resident.watch.snapshot()

    @app.get("/api/journal/open")
    def open_living_log(limit: int = 50) -> dict[str, Any]:
        """What went wrong and has not been dealt with.

        Its own endpoint rather than a filter on the one above, because it is
        a different question with a different reader. The pane shows history;
        this is the working list.
        """
        return {"entries": resident.journal.open_entries(limit=limit)}

    @app.post("/api/journal/{entry_id}/resolve")
    def resolve_living_log(entry_id: int, body: ResolveBody) -> dict[str, Any]:
        """Close one entry, with an account of what was done."""
        closed = resident.journal.resolve(
            entry_id, by=body.by.strip() or "owner", resolution=body.resolution
        )
        if closed is None:
            raise HTTPException(404, "No such Living Log entry")
        return closed

    @app.post("/api/log")
    def report_to_living_log(body: ReportBody, request: Request) -> dict[str, Any]:
        """**The channel an application uses to tell its Resident it is in trouble.**

        The direction the Living Log was named for, and the one it did not
        have. Everything else writing to it is AWORG watching itself; this is
        software the Resident built, running in the workspace, reporting its
        own failure without a person noticing first.

        Deliberately not under /api/journal. That is the owner interface's
        surface; this is the far narrower one a generated application is
        given, and keeping them apart is what lets the application's be
        authenticated differently and reasoned about on its own.

        A token, checked here. The spec is clear that prototype authority is
        not production security, so this is not an attempt at more than it
        looks -- but something will soon read this log on a schedule and act
        on it, and an open port on localhost would mean any process on this
        machine could wake the Resident at three in the morning. The token
        keeps the channel meaning "the applications AWORG started".
        """
        offered = (
            request.headers.get("x-aworg-token")
            or request.query_params.get("token")
            or ""
        )
        expected = report_token()
        # Compared in constant time out of habit rather than necessity. It
        # costs nothing and the habit is the point.
        if not secrets_module.compare_digest(offered, expected):
            raise HTTPException(401, "A valid AWORG_LOG_TOKEN is required.")

        entry = resident.journal.report(
            summary=body.summary,
            severity=body.severity,
            where=body.where,
            detail=body.detail,
            application=body.application,
        )
        if entry is None:
            raise HTTPException(400, "An event needs a summary saying what happened.")
        return entry

    def report_token() -> str:
        """The token applications report with, made once and kept.

        In the secret store beside the model credentials, because it is the
        same kind of thing: something AWORG holds on the owner's behalf that
        should not turn up in the state database they might send someone.

        Made on first use rather than at install, so an Aworg that never runs
        an application never has one.
        """
        held = secrets.get(journal_module.TOKEN_REF)
        if held:
            return held
        made = secrets_module.token_urlsafe(32)
        secrets.set(journal_module.TOKEN_REF, made)
        return made

    @app.delete("/api/journal")
    def clear_living_log() -> dict[str, int]:
        return {"removed": resident.journal.clear()}

    @app.get("/api/skills")
    def list_skills() -> dict[str, Any]:
        """What this Aworg knows how to do, and anything that would not load."""
        # Re-read on every request rather than at startup: a skill is a file,
        # and an owner who drops one into skills/ should see it without
        # restarting anything.
        resident.skills.discover()
        offered = resident.skills.offered()
        return {
            "skills": [
                {
                    **s.snapshot(),
                    "enabled": store.skill_enabled(s.name),
                    "offered": s in offered,
                }
                for s in resident.skills.all()
            ],
            "broken": resident.skills.broken,
        }

    @app.patch("/api/skills/{name}")
    def update_skill(name: str, body: CapabilityPatch) -> dict[str, Any]:
        """Switch a skill on or off.

        Reuses the capability patch shape because it is the same decision:
        one thing the owner has, and whether the Resident may reach for it.
        """
        if resident.skills.get_any(name) is None:
            raise HTTPException(404, "No such skill")
        store.set_skill_enabled(name, body.enabled)
        resident.journal.record(
            f"Skill {name} was {'enabled' if body.enabled else 'disabled'}",
            kind="skill",
            source="owner",
        )
        return {"name": name, "enabled": body.enabled}

    # -- tasks ----------------------------------------------------------

    @app.get("/api/tasks")
    def list_tasks(state: str = "open") -> list[dict[str, Any]]:
        if state == "all":
            return store.list_tasks()
        if state == "open":
            return store.list_tasks(store.OPEN_STATES)
        return store.list_tasks((state,))

    @app.patch("/api/tasks/{task_id}")
    def update_task(task_id: str, body: TaskPatch) -> dict[str, Any]:
        fields = {k: v for k, v in body.model_dump().items() if v is not None}
        updated = store.update_task(task_id, **fields)
        if updated is None:
            raise HTTPException(404, "No such task")
        return updated

    @app.delete("/api/tasks/{task_id}")
    def delete_task(task_id: str) -> dict[str, str]:
        if store.get_task(task_id) is None:
            raise HTTPException(404, "No such task")
        store.delete_task(task_id)
        return {"status": "deleted"}

    @app.post("/api/tasks/clear")
    def clear_tasks() -> dict[str, int]:
        """Forget finished tasks. Open ones are never touched."""
        return {"removed": store.clear_tasks()}

    # -- workers --------------------------------------------------------

    @app.get("/api/workers")
    def list_workers() -> list[dict[str, Any]]:
        return store.list_workers()

    @app.patch("/api/workers/{worker_id}")
    def update_worker(worker_id: str, body: WorkerPatch) -> dict[str, Any]:
        """Change a worker.

        Its description is worth as much care as its prompt: it is the only
        thing the Resident routes on, so editing it changes which jobs this
        worker gets. See docs/06_ARCHITECTURE.md.
        """
        fields = {k: v for k, v in body.model_dump().items() if v is not None}
        updated = store.update_worker(worker_id, **fields)
        if updated is None:
            raise HTTPException(404, "No such worker")
        return updated

    @app.post("/api/workers")
    def create_worker(body: WorkerBody) -> dict[str, Any]:
        return store.create_worker(
            name=body.name,
            description=body.description,
            connection_id=body.connection_id,
            system_prompt=body.system_prompt,
            tools=body.tools,
            skills=body.skills,
            enabled=body.enabled,
        )

    @app.delete("/api/workers/{worker_id}")
    def delete_worker(worker_id: str) -> dict[str, str]:
        if store.get_worker(worker_id) is None:
            raise HTTPException(404, "No such worker")
        store.delete_worker(worker_id)
        return {"status": "deleted"}

    # -- Activities -----------------------------------------------------

    @app.get("/api/activities")
    def list_activities() -> dict[str, Any]:
        """What is running now, and what recently was.

        Both, because the panel shows live work and the owner still wants to
        see the last thing that finished rather than an empty box the
        instant it does.
        """
        return {
            "live": resident.activities.live(),
            "recent": resident.activities.recent(30),
        }

    @app.get("/api/activities/stream")
    async def stream_activities() -> StreamingResponse:
        """Follow Activity lifecycle events as they are emitted.

        A subscriber in the sense the Activity Manager means: it is told
        what happened and decides for itself what that is worth. Here that
        decision is "draw it".
        """
        async def events():
            queue = resident.activities.subscribe()
            try:
                # The current picture first, so a browser that connects
                # mid-run sees what is already going rather than waiting for
                # something to change before the panel fills in.
                yield json.dumps(
                    {"event": "snapshot", "live": resident.activities.live()}
                ) + "\n"
                while True:
                    yield json.dumps(await queue.get()) + "\n"
            finally:
                resident.activities.unsubscribe(queue)

        return StreamingResponse(events(), media_type="application/x-ndjson")

    @app.get("/api/activities/{activity_id}/payload")
    def activity_payload(activity_id: str) -> dict[str, Any]:
        """The whole of what a tool returned, not the extract the model saw.

        This is the evidence half of the split. The conversation stores what
        was said -- sized to a window -- and this is what actually came back,
        for an owner who wants to check rather than take the Resident's word.
        """
        activity = resident.activities.get(activity_id)
        if activity is None:
            raise HTTPException(404, "No such activity, or it has been forgotten.")
        return {
            "id": activity.id,
            "label": activity.label,
            "state": activity.state,
            "summary": activity.summary,
            "error": activity.error,
            "payload": activity.payload if isinstance(activity.payload, str)
            else ("" if activity.payload is None else str(activity.payload)),
        }

    # -- the Living Workspace -------------------------------------------

    @app.get("/api/workspace")
    def workspace(path: str = "") -> dict[str, Any]:
        """List a directory inside the Living Workspace.

        The workspace is the Resident's territory, so the owner should be able
        to watch it change. Every path is resolved and checked for containment
        before anything is read -- the boundary is only meaningful if it is
        enforced here rather than assumed.
        """
        root = paths.workspace.resolve()
        target = (root / path).resolve() if path else root

        if target != root and root not in target.parents:
            raise HTTPException(400, "Outside the Living Workspace")
        if not target.is_dir():
            raise HTTPException(404, "No such directory")

        entries = []
        for child in sorted(target.iterdir(), key=lambda c: (c.is_file(), c.name.lower())):
            try:
                info = child.stat()
                is_dir = child.is_dir()
            except OSError:
                continue  # vanished mid-listing, or unreadable
            entries.append(
                {
                    "name": child.name,
                    "type": "directory" if is_dir else "file",
                    "size": None if is_dir else info.st_size,
                    "modified": datetime.fromtimestamp(info.st_mtime).isoformat(
                        timespec="seconds"
                    ),
                }
            )

        relative = "" if target == root else target.relative_to(root).as_posix()
        if target == root:
            parent = None
        elif target.parent == root:
            parent = ""
        else:
            parent = target.parent.relative_to(root).as_posix()

        return {
            "path": relative,
            "parent": parent,
            "entries": entries,
            "root": str(root),
        }

    #: The largest single file an owner may drop in.
    #:
    #: Bounded because a browser will cheerfully offer a four-gigabyte video
    #: and the stream is written straight to disk. Generous enough for what
    #: this is actually for: a logo, a spreadsheet, a spec, a sample database
    #: the Resident is meant to work from.
    MAX_UPLOAD_BYTES = 100 * 1024 * 1024

    def _safe_name(raw: str) -> str:
        """A filename that cannot be a path.

        Only the last component survives, so `../../.ssh/authorized_keys`
        becomes `authorized_keys` and lands where the owner was looking. The
        containment check on the folder is the real boundary; this is what
        stops a name being a path at all.
        """
        name = (raw or "").replace("\\", "/").split("/")[-1].strip()
        # Control characters and the Windows-reserved set, which would make a
        # file that cannot be opened or, worse, one whose name is a stream.
        name = "".join(c for c in name if c.isprintable() and c not in '<>:"|?*')
        return name.strip(". ")[:120]

    def _free_name(folder: Path, name: str) -> Path:
        """A path that does not exist yet, near the name that was asked for.

        Never overwrites. The Resident's files and the owner's drops share one
        directory, and silently replacing something a worker spent its whole
        context writing is not a cost worth paying to save the owner a rename.
        The interface says which name it actually got.
        """
        target = folder / name
        if not target.exists():
            return target
        stem, dot, suffix = name.partition(".")
        for n in range(2, 1000):
            candidate = folder / f"{stem} ({n}){dot}{suffix}"
            if not candidate.exists():
                return candidate
        raise HTTPException(409, "There are too many files by that name already.")

    @app.post("/api/workspace/upload")
    async def upload_to_workspace(
        request: Request, path: str = "", name: str = ""
    ) -> dict[str, Any]:
        """Take a file the owner dropped onto the Living Workspace.

        **The raw body carries the file, not a multipart form.** That is a
        dependency decision rather than a stylistic one: FastAPI's UploadFile
        needs python-multipart, which would be a fourth dependency for
        something a browser can already express as a POST with bytes in it.
        One request per file, and the name rides in the query string.

        Streamed to disk rather than read whole, so the cap is enforced as it
        arrives instead of after the machine has already held all of it.

        Written under a dotted temporary name and moved into place at the end.
        The workspace is polled every second by the owner's own interface and
        read by the Resident, and a half-written file that appears in either as
        though it were finished is a file somebody acts on too early.
        """
        root = paths.workspace.resolve()
        folder = (root / path).resolve() if path else root
        if folder != root and root not in folder.parents:
            raise HTTPException(400, "Outside the Living Workspace")
        if not folder.is_dir():
            raise HTTPException(404, "No such directory")

        safe = _safe_name(name)
        if not safe:
            raise HTTPException(400, "That file needs a name.")

        target = _free_name(folder, safe)
        partial = folder / f".{target.name}.part"
        written = 0
        try:
            with partial.open("wb") as handle:
                async for chunk in request.stream():
                    written += len(chunk)
                    if written > MAX_UPLOAD_BYTES:
                        raise HTTPException(
                            413,
                            "That file is larger than "
                            f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
                        )
                    handle.write(chunk)
            partial.replace(target)
        except HTTPException:
            partial.unlink(missing_ok=True)
            raise
        except OSError as exc:
            partial.unlink(missing_ok=True)
            raise HTTPException(500, f"It could not be written: {exc}") from None

        # So the Resident finds out. An owner who drops a spec into the
        # workspace and says nothing has still told it something, and without
        # this the file sits there until somebody mentions it in conversation.
        where = target.relative_to(root).as_posix()
        resident.journal.record(
            f"You added {target.name}",
            kind="workspace",
            source="owner",
            detail=f"Dropped into the Living Workspace at {where}, {written:,} bytes.",
        )

        return {"name": target.name, "path": where, "size": written}

    #: Ports a served application is most likely to be on. Guessing is
    #: acceptable here in a way it is not elsewhere, because being wrong
    #: costs a preview that does not appear rather than a false claim -- and
    #: the alternative is asking the owner to type a port for something the
    #: Resident chose.
    PREVIEW_PORTS = (8000, 3000, 5173, 8080, 5000, 4200, 8888)

    def _served_port(record: Any) -> int | None:
        """Which port this process is serving on, if any.

        **The command line is the weaker source and was the only one.** It
        works for `python -m http.server 8000`, where the port is an argument,
        and not at all for a real application -- a server that knows its own
        port has nothing in its command line to find. So a generated app, the
        entire point of the MVP, was invisible: the preview said nothing was
        running and the Lifecycle read "being built" while the site answered
        on 8000 and a WebSocket endpoint answered on 8765.

        What the process *said* is the better evidence, and AWORG already has
        it -- output is drained continuously so a full pipe cannot block the
        program, and the first thing nearly every server prints is where it
        is listening. So the output is read first and the command line is the
        fallback.
        """
        for source in (_recent_output(record), record.command):
            for found in re.finditer(r"(?<![\d.])(\d{4,5})(?![\d.])", source or ""):
                port = int(found.group(1))
                if port in PREVIEW_PORTS:
                    return port
        return None

    def _recent_output(record: Any) -> str:
        """The opening lines a process printed, where it says where it is.

        The start rather than the end: "Serving HTTP on 0.0.0.0 port 8000" is
        the first thing said, and by the hundredth request the tail is all
        access logs -- which carry client ports and would name the wrong one.
        """
        try:
            return "\n".join(list(record.lines)[:12])
        except Exception:                                  # noqa: BLE001
            return ""

    def serving_now() -> dict[str, Any] | None:
        """A process AWORG started that is alive on a plausible port.

        Shared by the preview and the Lifecycle stepper deliberately. Two
        separate answers to "is it running" is two chances to disagree, and
        the pane showing a page while the stepper says "being built" would
        leave the owner with no idea which to believe.
        """
        for record in resident.processes.all():
            if not record.alive:
                continue
            port = _served_port(record)
            if port is None:
                continue
            return {
                "id": record.id,
                "label": record.label,
                "port": port,
                "uptime": record.uptime,
            }
        return None

    #: The last fetch AWORG made of the served application, and what the
    #: workspace looked like when it made it. Held rather than repeated,
    #: because the Lifecycle stepper is polled and an outbound request per
    #: poll would be AWORG hammering the Resident's own application.
    last_check: dict[str, Any] = {}

    #: How long a fetch of the application is allowed to take. Short: this
    #: runs on a path the interface polls, and a hung application must not
    #: become a hung owner interface.
    CHECK_TIMEOUT = 2.0

    def workspace_changed_at() -> float:
        """When the Living Workspace was last touched.

        The newest modification time under it. That is the moment "the
        application as it now stands" begins, and any check older than it
        was a check of something else.
        """
        workspace = paths.workspace
        if not workspace.exists():
            return 0.0
        newest = 0.0
        for item in workspace.rglob("*"):
            try:
                newest = max(newest, item.stat().st_mtime)
            except OSError:
                continue
        return newest

    def answered_now(serving: dict[str, Any] | None) -> dict[str, Any] | None:
        """AWORG's own fetch of the application, made after the last change.

        **The point is who is doing the looking.** The Resident saying it
        checked its work is testimony from the party being judged; this is
        AWORG opening the application itself and seeing what comes back. That
        is the same argument the whole Lifecycle stepper is built on, carried
        one stage further than it previously went.

        Re-fetched only when the workspace has changed since the last look,
        so an idle Aworg makes no requests at all and a busy one makes one
        per change rather than one per poll.
        """
        if not serving:
            return None
        port = serving.get("port")
        changed = workspace_changed_at()
        held = last_check.get(port)
        if held and held["changed"] >= changed:
            return held["result"]

        result: dict[str, Any] | None = None
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/", timeout=CHECK_TIMEOUT
            ) as answer:
                # Any 2xx. A directory listing is a served application as far
                # as this stage is concerned -- whether it is the *right*
                # application is the checker's job and not a stepper's.
                result = {"status": answer.status, "at": time.time()}
        except Exception:                                  # noqa: BLE001
            # Refused, timed out, 500 -- all the same answer here: the thing
            # that is running did not answer for the application as it now
            # stands. The stage drops back and the owner sees it.
            result = None

        last_check[port] = {"changed": changed, "result": result}
        return result

    @app.get("/api/preview")
    def preview() -> dict[str, Any]:
        """Where the owner watches the Resident's application run.

        Derived from what is actually running rather than from anything the
        Resident said about it. "I started the server" is not evidence; this
        pane showing a page is the owner's own confirmation that it worked.

        **Asks serving_now rather than working it out again.** That function's
        docstring has always said the two share an answer, because two answers
        to "is it running" are two chances to disagree -- and they disagreed:
        this endpoint carried its own copy of the port-finding, so when the
        copy stopped matching, the Lifecycle read "verified, fetched on port
        8000" while the pane beside it said nothing was running. The owner had
        no way to tell which to believe, which is the exact failure the
        sharing was meant to prevent.
        """
        serving = serving_now()
        if not serving:
            return {
                "available": False,
                "url": None,
                "detail": "Nothing running to show",
                "hint": (
                    "When your Resident starts something that serves a page, "
                    "it appears here."
                ),
            }
        return {
            "available": True,
            "url": f"http://127.0.0.1:{serving['port']}/",
            "detail": serving["label"],
            "hint": f"Served by {serving['id']}, running for {serving['uptime']:.0f}s.",
            # What the owner is looking at, as a value that changes when it
            # stops being current. The URL alone is not enough: it does not
            # change when the files behind it do, so the preview went on
            # showing the page from before an edit.
            "revision": f"{workspace_changed_at():.0f}:{resident.preview_revision}",
        }

    # Mounted last so the API routes above take precedence.
    @app.get("/", include_in_schema=False)
    def index() -> Response:
        """The page, with its assets stamped by their own modification time.

        Browsers hold on to a script they have already fetched, and AWORG is
        a long-running program that gets updated underneath a tab someone
        left open. Without this, an owner who updates and reloads gets the
        new server and the old interface, which fails in ways that look like
        bugs in neither.

        Stamped by mtime rather than by AWORG's version, because the version
        does not change between the edit and the reload -- and this has to be
        right for whoever is working on the interface as much as for whoever
        is running it.
        """
        html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        for asset in ("app.js", "style.css", "markdown.js", "highlight.js"):
            path = WEB_DIR / asset
            if not path.exists():
                continue
            stamp = int(path.stat().st_mtime)
            html = html.replace(f'"/{asset}"', f'"/{asset}?v={stamp}"')
        return Response(
            html,
            media_type="text/html",
            # The page itself is never cached; everything it names is, and
            # is re-fetched precisely when it changes.
            headers={"Cache-Control": "no-store"},
        )

    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")

    return app
