"""Save, test, list or forget named database connections."""

from __future__ import annotations

import asyncio
import re

from aworg.tools.base import ToolContext, ToolError, ToolResult

from ._db import hide_password, kind_of, open_connection, save, saved

NAME = "db_connect"

DESCRIPTION = (
    "Save a database connection under a name and test it, or list the saved "
    "ones. Other database tools refer to a connection by this name. URLs: "
    "sqlite:///path/to/file.db (relative paths are in the workspace), "
    "postgresql://user:password@host:5432/db, mysql://user:password@host:3306/db."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "A short name for the connection."},
        "url": {"type": "string", "description": "The connection URL. Omit to just list saved connections."},
        "forget": {"type": "boolean", "description": "Remove the named connection instead."},
    },
}


async def run(context: ToolContext, name: str = "", url: str = "", forget: bool = False) -> ToolResult:
    connections = saved()
    name = str(name or "").strip()

    if forget:
        if name not in connections:
            raise ToolError(f"No connection called {name!r}.")
        del connections[name]
        save(connections)
        return ToolResult(text=f"Forgot {name}.", summary=f"forgot {name}")

    if not url:
        if not connections:
            return ToolResult(text="No connections saved.", summary="none")
        lines = [f"{n}: {hide_password(u)}" for n, u in connections.items()]
        return ToolResult(text="\n".join(lines), summary=f"{len(lines)} saved")

    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", name):
        raise ToolError("Give a name of 1-40 letters, digits, '-' or '_'.")
    url = str(url).strip()
    kind = kind_of(url)
    workspace = getattr(getattr(context, "paths", None), "workspace", None)

    def test():
        conn = open_connection(url, workspace, read_only=False)
        conn.close()

    try:
        await asyncio.to_thread(test)
    except ToolError:
        raise
    except Exception as exc:                                  # noqa: BLE001
        raise ToolError(f"Could not connect ({kind}): {exc}") from None

    connections[name] = url
    save(connections)
    return ToolResult(text=f"Saved {name} ({kind}) and connected to it.", summary=f"{name}: {kind}")
