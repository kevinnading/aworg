"""See how workers are doing, and read what they replied."""

from __future__ import annotations

import time

from ..base import ToolContext, ToolError, ToolResult


NAME = "check_workers"

DESCRIPTION = (
    "List your workers and their state, or name one to read its reply and "
    "the tool calls it made. You do not need this to hear "
    "from a worker: end your reply, and each finished worker's reply arrives "
    "as the next message. This is for one that seems to be taking too long."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "worker": {
            "type": "string",
            "description": "A worker's id, to read that one in full.",
        },
    },
}

#: Under this, a working worker is reported as only just started.
EARLY = 60


def _early(workers) -> str:
    """A note for any worker still working that started under EARLY seconds ago."""
    now = time.time()
    young = [
        f"{w.id} has only been working {int(now - w.run_started)} seconds"
        for w in workers
        if w.state == w.WORKING and now - w.run_started < EARLY
    ]
    if not young:
        return ""
    return (
        "\n\n" + "; ".join(young) + ". End your reply and you will be told "
        "automatically when it finishes."
    )


async def run(context: ToolContext, worker: str = "") -> ToolResult:
    pool = getattr(context, "workers", None)
    if pool is None:
        raise ToolError("Workers are not wired up in this Aworg.")

    if str(worker).strip():
        try:
            one = pool.get(worker)
        except KeyError as exc:
            raise ToolError(str(exc.args[0])) from None
        return ToolResult(text=one.take() + _early([one]),
                          summary=f"{one.id}: {one.state}")

    everyone = pool.all()
    if not everyone:
        return ToolResult(text="No workers.", summary="none")
    return ToolResult(
        text="\n".join(w.line() for w in everyone) + _early(everyone),
        summary=", ".join(f"{w.id} {w.state}" for w in everyone),
    )
