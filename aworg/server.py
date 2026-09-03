"""The owner interface's backing service.

Everything the owner interface can do goes through here. The Resident is not
exposed directly; the API is the controlled surface in front of it, which is
the shape the Resident API will eventually need when generated applications
are allowed to talk to a Resident under far tighter restrictions.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .models import CAPABILITY_TAGS, PROVIDER_LABELS, ModelError, build_adapter
from .paths import Paths
from .resident import Resident
from .secrets import SecretStore, credential_ref
from . import layout as layout_settings
from . import lifecycle, panes
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


class ResidentPatch(BaseModel):
    primary_connection_id: str | None = None
    worker_connection_id: str | None = None
    system_prompt: str | None = None


class ChatBody(BaseModel):
    message: str


class AppearancePatch(BaseModel):
    preset: str | None = None
    overrides: dict[str, str] | None = None


class LayoutPatch(BaseModel):
    #: The whole set of dragged sizes. An empty object resets the view.
    #:
    #: Deliberately untyped past "an object". Declaring int here would make
    #: pydantic refuse the entire request over one bad value, which is the
    #: opposite of what is wanted: one stale or malformed pane should be
    #: dropped, not take a good layout down with it. layout.sanitize is the
    #: single gate, and it is strict.
    sizes: dict[str, Any]


def create_app(paths: Paths) -> FastAPI:
    paths.ensure()
    store = Store(paths.state_db)
    secrets = SecretStore(paths.secrets_db)
    resident = Resident(store, secrets)

    app = FastAPI(title="AWORG", version="0.1.0")

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
            "capability_tags": CAPABILITY_TAGS,
            "home": str(paths.home),
        }

    @app.get("/api/state")
    def state() -> dict[str, Any]:
        config = store.get_resident()
        return {
            "resident": resident.state(),
            "primary_connection_id": config["primary_connection_id"],
            "worker_connection_id": config["worker_connection_id"],
            "system_prompt": config["system_prompt"],
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

    @app.post("/api/chat")
    async def chat(body: ChatBody) -> StreamingResponse:
        text = body.message.strip()
        if not text:
            raise HTTPException(400, "Empty message")

        async def events():
            async for event in resident.respond_to(text):
                yield json.dumps(event) + "\n"

        return StreamingResponse(events(), media_type="application/x-ndjson")

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
        return Response(
            content=":root {\n" + colors + sizes + "}\n",
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
        return lifecycle.assess(workspace_has_files())

    @app.get("/api/panes")
    def status_panes() -> list[dict[str, Any]]:
        """Every pane in the status column, and what it currently holds.

        One request rather than seven. These are read together, and they
        stay together until one of them grows enough to want its own.
        """
        return panes.describe()

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

    @app.get("/api/preview")
    def preview() -> dict[str, Any]:
        """Where the owner watches the Resident's application run.

        Nothing can be running yet -- the Resident gains the ability to build
        and start software in Milestone 2. Saying so plainly is better than an
        empty frame that looks broken.
        """
        return {
            "available": False,
            "url": None,
            "detail": "No preview available",
            "hint": "Your Resident cannot build or run applications yet.",
        }

    # Mounted last so the API routes above take precedence.
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")

    return app
