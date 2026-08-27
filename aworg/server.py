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
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .models import CAPABILITY_TAGS, PROVIDER_LABELS, ModelError, build_adapter
from .paths import Paths
from .resident import Resident
from .secrets import SecretStore, credential_ref
from .storage import Store


WEB_DIR = Path(__file__).parent / "web"


class ConnectionBody(BaseModel):
    name: str
    provider: str
    model: str
    base_url: str | None = None
    tags: list[str] = []
    enabled: bool = True
    credential: str | None = None


class ConnectionPatch(BaseModel):
    name: str | None = None
    provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    tags: list[str] | None = None
    enabled: bool | None = None
    credential: str | None = None


class ResidentPatch(BaseModel):
    primary_connection_id: str | None = None
    system_prompt: str | None = None


class ChatBody(BaseModel):
    message: str


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
        try:
            await build_adapter(connection, api_key).probe()
        except ModelError as exc:
            return {"ok": False, "detail": str(exc)}
        return {"ok": True, "detail": "Reached the model successfully."}

    # -- the Resident ---------------------------------------------------

    @app.patch("/api/resident")
    def update_resident(body: ResidentPatch) -> dict[str, Any]:
        fields: dict[str, Any] = {}
        if body.primary_connection_id is not None:
            if store.get_connection(body.primary_connection_id) is None:
                raise HTTPException(404, "No such connection")
            fields["primary_connection_id"] = body.primary_connection_id
        if body.system_prompt is not None:
            fields["system_prompt"] = body.system_prompt
        if fields:
            store.update_resident(**fields)
        return {"resident": resident.state(), **store.get_resident()}

    @app.get("/api/conversation")
    def conversation() -> dict[str, Any]:
        return resident.conversation()

    @app.post("/api/conversation/new")
    def new_conversation() -> dict[str, Any]:
        return resident.new_conversation()

    @app.post("/api/chat")
    async def chat(body: ChatBody) -> StreamingResponse:
        text = body.message.strip()
        if not text:
            raise HTTPException(400, "Empty message")

        async def events():
            async for event in resident.respond_to(text):
                yield json.dumps(event) + "\n"

        return StreamingResponse(events(), media_type="application/x-ndjson")

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
