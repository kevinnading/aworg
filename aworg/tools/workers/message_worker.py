"""Send a worker further."""

from __future__ import annotations

from ..base import ToolContext, ToolError, ToolResult


NAME = "message_worker"

DESCRIPTION = (
    "Send a worker that has replied another message. It continues with "
    "everything it already has, in the background."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "worker": {"type": "string", "description": "The worker's id."},
        "message": {"type": "string", "description": "What to tell it."},
    },
    "required": ["worker", "message"],
}


async def run(context: ToolContext, worker: str = "", message: str = "") -> ToolResult:
    pool = getattr(context, "workers", None)
    if pool is None:
        raise ToolError("Workers are not wired up in this Aworg.")
    if not str(message).strip():
        raise ToolError("No message was given.")
    try:
        one = pool.message(worker, str(message))
    except KeyError as exc:
        raise ToolError(str(exc.args[0])) from None
    except ValueError as exc:
        raise ToolError(str(exc)) from None
    return ToolResult(text=f"Worker {one.id} is working again.", summary=f"{one.id} working")
