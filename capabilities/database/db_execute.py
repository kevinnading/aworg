"""Change a database: insert, update, delete, create, alter."""

from __future__ import annotations

import asyncio

from aworg.tools.base import ToolContext, ToolError, ToolResult

from ._db import open_connection, resolve

NAME = "db_execute"

DESCRIPTION = (
    "Run SQL that changes a saved database -- INSERT, UPDATE, DELETE, CREATE, "
    "ALTER, DROP -- and commit it. Several statements may be separated by "
    "semicolons; they run together and all are undone if one fails."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "connection": {"type": "string", "description": "The saved connection's name."},
        "sql": {"type": "string", "description": "The statement or statements."},
    },
    "required": ["connection", "sql"],
}


def _statements(sql: str) -> list[str]:
    """Split on semicolons outside quotes."""
    out, buf, quote = [], [], None
    for ch in sql:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            buf.append(ch)
        elif ch == ";":
            if "".join(buf).strip():
                out.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if "".join(buf).strip():
        out.append("".join(buf).strip())
    return out


async def run(context: ToolContext, connection: str = "", sql: str = "") -> ToolResult:
    statements = _statements(str(sql))
    if not statements:
        raise ToolError("No SQL was given.")
    url = resolve(str(connection).strip())
    workspace = getattr(getattr(context, "paths", None), "workspace", None)

    def go():
        conn = open_connection(url, workspace, read_only=False)
        try:
            cur = conn.cursor()
            counts = []
            for s in statements:
                cur.execute(s)
                counts.append(cur.rowcount)
            conn.commit()
            return counts
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    try:
        counts = await asyncio.to_thread(go)
    except ToolError:
        raise
    except Exception as exc:                                  # noqa: BLE001
        raise ToolError(f"Nothing was changed: {exc}") from None
    affected = sum(c for c in counts if c and c > 0)
    return ToolResult(
        text=f"Committed {len(statements)} statement{'s' if len(statements) != 1 else ''}; "
             f"{affected} row{'s' if affected != 1 else ''} affected.",
        summary=f"{affected} rows",
    )
