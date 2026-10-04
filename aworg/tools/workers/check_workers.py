"""See how workers are doing, and read what they replied."""

from __future__ import annotations

from ..base import ToolContext, ToolError, ToolResult


NAME = "check_workers"

DESCRIPTION = (
    "List your workers and their state: working, replied or failed. Name "
    "one to read its reply and the tool calls AWORG observed it make."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "worker": {
            "type": "string",
            "description": "A worker's id, to read that one in full.",
        },
        "wait": {
            "type": "number",
            "description": (
                "Seconds to wait first for a working worker to finish -- the "
                "named one, or any. Defaults to 0."
            ),
        },
    },
}


async def run(context: ToolContext, worker: str = "", wait: float = 0) -> ToolResult:
    pool = getattr(context, "workers", None)
    if pool is None:
        raise ToolError("Workers are not wired up in this Aworg.")
    try:
        seconds = max(0.0, float(wait or 0))
    except (TypeError, ValueError):
        raise ToolError("wait must be a number of seconds.") from None

    if str(worker).strip():
        try:
            one = pool.get(worker)
        except KeyError as exc:
            raise ToolError(str(exc.args[0])) from None
        await pool.wait([one], seconds)
        return ToolResult(text=one.take(), summary=f"{one.id}: {one.state}")

    everyone = pool.all()
    await pool.wait(everyone, seconds)
    if not everyone:
        return ToolResult(text="No workers.", summary="none")
    return ToolResult(
        text="\n".join(w.line() for w in everyone),
        summary=", ".join(f"{w.id} {w.state}" for w in everyone),
    )
