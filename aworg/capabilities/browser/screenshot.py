"""Take a picture of the open page, for the owner to look at."""

from __future__ import annotations

import base64
from datetime import datetime

from aworg.tools.base import ToolContext, ToolError, ToolResult, resolve_path

from ._cdp import BrowserError, browser


NAME = "screenshot"

DESCRIPTION = (
    "Save a picture of the page that is open, as a PNG in the Living "
    "Workspace. For showing the owner what something looks like -- you "
    "cannot see the image yourself, so use read_page to find out what the "
    "page says."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": (
                "Where to save it. Relative paths land in the Living "
                "Workspace. Defaults to a dated name there."
            ),
        },
        "full_page": {
            "type": "boolean",
            "description": (
                "Capture the whole scrollable page rather than just what "
                "fits on screen. Defaults to false."
            ),
        },
    },
}


async def run(
    context: ToolContext,
    path: str | None = None,
    full_page: bool = False,
) -> ToolResult:
    try:
        page_browser = await browser(start_if_needed=False)
        shot = await page_browser.command("Page.captureScreenshot", {
            "format": "png",
            "captureBeyondViewport": bool(full_page),
        })
    except BrowserError as exc:
        raise ToolError(str(exc)) from exc

    data = shot.get("data")
    if not data:
        raise ToolError("The browser returned an empty screenshot.")

    name = path or f"screenshot-{datetime.now():%Y%m%d-%H%M%S}.png"
    if not name.lower().endswith(".png"):
        name += ".png"
    destination = resolve_path(context, name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        destination.write_bytes(base64.b64decode(data))
    except OSError as exc:
        raise ToolError(f"Could not save the screenshot: {exc}") from exc

    size = destination.stat().st_size
    return ToolResult(
        # Said plainly, because a model that believes it has looked at the
        # page will describe an image it has never seen.
        text=(
            f"Saved a picture of {page_browser.url} to {destination} "
            f"({size // 1024} KB). You cannot see it; it is there for the "
            f"owner. Use read_page to find out what the page actually says."
        ),
        payload={"path": str(destination), "bytes": size, "url": page_browser.url},
        summary=f"{size // 1024} KB png",
    )
