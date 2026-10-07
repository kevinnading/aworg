"""Read from a database. The connection is opened read-only."""

from __future__ import annotations

import asyncio

from aworg.tools.base import ToolContext, ToolError, ToolResult

from ._db import open_connection, resolve, table

NAME = "db_query"

DESCRIPTION = (
    "Run a read-only SQL query on a saved connection and get the rows back. "
    "The connection is opened read-only, so a query that would change data "
    "fails. Use db_execute to write."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "connection": {"type": "string", "description": "The saved connection's name."},
        "sql": {"type": "string", "description": "The query."},
        "limit": {"type": "integer", "description": "Most rows to return, up to 1000. Defaults to 100."},
    },
    "required": ["connection", "sql"],
}


async def run(context: ToolContext, connection: str = "", sql: str = "", limit: int = 100) -> ToolResult:
    if not str(sql).strip():
        raise ToolError("No SQL was given.")
    try:
        limit = max(1, min(1000, int(limit or 100)))
    except (TypeError, ValueError):
        limit = 100
    url = resolve(str(connection).strip())
    workspace = getattr(getattr(context, "paths", None), "workspace", None)

    def go():
        conn = open_connection(url, workspace, read_only=True)
        try:
            cur = conn.cursor()
            cur.execute(sql)
            if cur.description is None:
                return None, [], False
            columns = [d[0] for d in cur.description]
            rows = cur.fetchmany(limit + 1)
            return columns, [tuple(r) for r in rows], len(rows) > limit
        finally:
            try:
                conn.rollback()
            except Exception:                                 # noqa: BLE001
                pass
            conn.close()

    try:
        columns, rows, more = await asyncio.to_thread(go)
    except ToolError:
        raise
    except Exception as exc:                                  # noqa: BLE001
        raise ToolError(f"{exc}") from None
    if columns is None:
        return ToolResult(text="The statement returned no rows.", summary="no rows")
    text = table(columns, rows, limit)
    shown = min(len(rows), limit)
    tail = f"\n\n{shown} rows shown; there are more." if more else f"\n\n{shown} row{'s' if shown != 1 else ''}."
    return ToolResult(text=text + tail, summary=f"{shown}{'+' if more else ''} rows")
