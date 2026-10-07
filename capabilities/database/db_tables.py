"""List the tables in a saved database."""

from __future__ import annotations

import asyncio

from aworg.tools.base import ToolContext, ToolError, ToolResult

from ._db import kind_of, open_connection, resolve

NAME = "db_tables"

DESCRIPTION = "List the tables and views in a saved database connection."

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "connection": {"type": "string", "description": "The saved connection's name."},
    },
    "required": ["connection"],
}

SQL = {
    "sqlite": "SELECT name, type FROM sqlite_master WHERE type IN ('table','view') "
              "AND name NOT LIKE 'sqlite_%' ORDER BY name",
    "postgresql": "SELECT table_schema || '.' || table_name, table_type FROM information_schema.tables "
                  "WHERE table_schema NOT IN ('pg_catalog','information_schema') ORDER BY 1",
    "mysql": "SELECT table_name, table_type FROM information_schema.tables "
             "WHERE table_schema = DATABASE() ORDER BY 1",
}


async def run(context: ToolContext, connection: str = "") -> ToolResult:
    url = resolve(str(connection).strip())
    kind = kind_of(url)
    workspace = getattr(getattr(context, "paths", None), "workspace", None)

    def go():
        conn = open_connection(url, workspace, read_only=True)
        try:
            cur = conn.cursor()
            cur.execute(SQL[kind])
            return cur.fetchall()
        finally:
            conn.close()

    try:
        rows = await asyncio.to_thread(go)
    except ToolError:
        raise
    except Exception as exc:                                  # noqa: BLE001
        raise ToolError(f"{exc}") from None
    if not rows:
        return ToolResult(text="No tables.", summary="0 tables")
    return ToolResult(
        text="\n".join(f"{name} ({str(kind_).lower()})" for name, kind_ in rows),
        summary=f"{len(rows)} tables",
    )
