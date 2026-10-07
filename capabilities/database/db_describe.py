"""The columns of one table."""

from __future__ import annotations

import asyncio
import re

from aworg.tools.base import ToolContext, ToolError, ToolResult

from ._db import kind_of, open_connection, resolve, table

NAME = "db_describe"

DESCRIPTION = "Show one table's columns: name, type, whether it may be null, default, and key."

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "connection": {"type": "string", "description": "The saved connection's name."},
        "table": {"type": "string", "description": "The table, as db_tables lists it."},
    },
    "required": ["connection", "table"],
}


async def run(context: ToolContext, connection: str = "", table_name: str = "", **kw) -> ToolResult:
    name = str(kw.get("table") or table_name).strip()
    if not re.fullmatch(r"[A-Za-z0-9_.$-]{1,128}", name):
        raise ToolError("Give a table name as db_tables lists it.")
    url = resolve(str(connection).strip())
    kind = kind_of(url)
    workspace = getattr(getattr(context, "paths", None), "workspace", None)

    def go():
        conn = open_connection(url, workspace, read_only=True)
        try:
            cur = conn.cursor()
            if kind == "sqlite":
                cur.execute(f'PRAGMA table_info("{name}")')
                rows = [(r[1], r[2], "no" if r[3] else "yes", r[4], "primary" if r[5] else "") for r in cur.fetchall()]
            else:
                schema, _, tbl = name.rpartition(".")
                where = "table_name = %s" + (" AND table_schema = %s" if schema else
                                             (" AND table_schema = DATABASE()" if kind == "mysql" else ""))
                params = (tbl, schema) if schema else (tbl,)
                cur.execute(
                    "SELECT column_name, data_type, is_nullable, column_default, "
                    + ("column_key" if kind == "mysql" else "''")
                    + f" FROM information_schema.columns WHERE {where} ORDER BY ordinal_position",
                    params,
                )
                rows = [tuple(r) for r in cur.fetchall()]
            return rows
        finally:
            conn.close()

    try:
        rows = await asyncio.to_thread(go)
    except ToolError:
        raise
    except Exception as exc:                                  # noqa: BLE001
        raise ToolError(f"{exc}") from None
    if not rows:
        raise ToolError(f"No table called {name!r}, or it has no columns.")
    return ToolResult(
        text=table(["column", "type", "nullable", "default", "key"], rows, len(rows)),
        summary=f"{len(rows)} columns",
    )
