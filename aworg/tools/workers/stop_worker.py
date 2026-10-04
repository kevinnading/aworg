"""Stop a worker and discard it."""

from __future__ import annotations

from ..base import ToolContext, ToolError, ToolResult


NAME = "stop_worker"

DESCRIPTION = "Stop a worker and discard it. One still working is cancelled."

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "worker": {"type": "string", "description": "The worker's id."},
    },
    "required": ["worker"],
}


async def run(context: ToolContext, worker: str = "") -> ToolResult:
    pool = getattr(context, "workers", None)
    if pool is None:
        raise ToolError("Workers are not wired up in this Aworg.")
    try:
        one = pool.stop(worker)
    except KeyError as exc:
        raise ToolError(str(exc.args[0])) from None
    return ToolResult(text=f"Worker {one.id} stopped.", summary=f"{one.id} stopped")
