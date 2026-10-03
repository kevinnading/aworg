"""Shut the browser, when it is no longer being used."""

from __future__ import annotations

from aworg.tools.base import ToolContext, ToolResult

from ._cdp import _browser


NAME = "close_browser"

DESCRIPTION = (
    "Close the browser and free what it is holding. The next open_page starts"
    " a fresh one."
)

INPUT_SCHEMA = {"type": "object", "properties": {}}


async def run(context: ToolContext) -> ToolResult:
    # Not an error when nothing is open. A tool whose job is to make sure
    # something is not running should be safe to call without checking
    # first, or the model learns to check first -- which is another turn
    # spent on bookkeeping.
    if not _browser.running:
        return ToolResult(text="No browser was open.", summary="already closed")

    was = _browser.url or "about:blank"
    # Nothing is passed in: the browser is holding the table it was given
    # when it started, which is the one that has the row to clear.
    await _browser.stop()
    return ToolResult(
        text=f"Closed the browser. It was showing {was}.",
        summary="closed",
    )
