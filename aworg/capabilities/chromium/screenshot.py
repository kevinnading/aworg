"""Take a picture of the open page -- and look at it.

Two things at once, on purpose. The PNG goes to the Living Workspace at full
size, because that one is for the owner: it is what gets shown, attached, or
compared against later. A second, smaller JPEG comes back attached to the
result, because that one is for the Resident, and a model reading a
four-megabyte screenshot pays for every pixel of a resolution it cannot use.

Looking costs real tokens -- roughly a thousand per picture, every time the
conversation is sent afterwards -- so `show` can be turned off when the point
is to leave the owner an image rather than to see the page. Reading the page
with read_page is still cheaper and more precise for anything made of words.
What a picture is for is the question words cannot answer: whether it looks
right.
"""

from __future__ import annotations

import base64
from datetime import datetime

from aworg.tools.base import ToolContext, ToolError, ToolResult, resolve_path

from ._cdp import BrowserError, browser


NAME = "screenshot"

DESCRIPTION = (
    "Take a picture of the page that is open: saved as a PNG in the Living "
    "Workspace for the owner, and shown to you so you can see what the page "
    "looks like. Use it to check layout, spacing and whether something "
    "renders correctly -- for reading the page, read_page is cheaper and "
    "more exact."
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
        "show": {
            "type": "boolean",
            "description": (
                "Show the picture to you as well as saving it. Defaults to "
                "true. Turn it off when the owner wants the file but you do "
                "not need to look."
            ),
        },
    },
}

#: What the copy sent to the model is scaled to. Wide enough that layout,
#: spacing and text are all legible, small enough that the picture is worth
#: what it costs -- roughly a thousand tokens rather than several thousand.
LOOK_WIDTH = 900
LOOK_QUALITY = 62
#: A page thirty screens tall is not a picture worth sending; clipped rather
#: than refused, because the top of a long page is usually the question.
MAX_LOOK_HEIGHT = 2400


async def run(
    context: ToolContext,
    path: str | None = None,
    full_page: bool = False,
    show: bool = True,
) -> ToolResult:
    try:
        page_browser = await browser(start_if_needed=False)
        keep = await page_browser.command("Page.captureScreenshot", {
            "format": "png",
            "captureBeyondViewport": bool(full_page),
        })
        look = await _for_the_model(page_browser, full_page) if show else None
    except BrowserError as exc:
        raise ToolError(str(exc)) from exc

    data = keep.get("data")
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
    told = (
        f"Here is {page_browser.url}. The full-size picture is saved at "
        f"{destination} ({size // 1024} KB) for the owner."
        if look else
        f"Saved a picture of {page_browser.url} to {destination} "
        f"({size // 1024} KB). You have not been shown it -- pass show=true "
        f"if you need to see the page."
    )

    return ToolResult(
        text=told,
        payload={"path": str(destination), "bytes": size, "url": page_browser.url},
        summary=f"{size // 1024} KB png" + (", looked" if look else ""),
        images=[{"media_type": "image/jpeg", "data": look}] if look else [],
    )


async def _for_the_model(page_browser, full_page: bool) -> str | None:
    """A smaller JPEG of the same page, or None if it could not be made.

    Scaled by the browser rather than by AWORG, because resizing an image in
    Python means an imaging library, and a capability that made an owner
    install Pillow to look at a page would be one they did not install.
    Chromium can do it while it captures, which is also faster.
    """
    metrics = await page_browser.command("Page.getLayoutMetrics")
    viewport = metrics.get("cssLayoutViewport") or {}
    content = metrics.get("cssContentSize") or {}
    width = int((content if full_page else viewport).get("clientWidth")
                or content.get("width") or LOOK_WIDTH)
    height = int((content if full_page else viewport).get("clientHeight")
                 or content.get("height") or LOOK_WIDTH)
    if width <= 0 or height <= 0:
        return None

    scale = min(1.0, LOOK_WIDTH / width)
    height = min(height, int(MAX_LOOK_HEIGHT / scale))
    shot = await page_browser.command("Page.captureScreenshot", {
        "format": "jpeg",
        "quality": LOOK_QUALITY,
        "captureBeyondViewport": bool(full_page),
        "clip": {"x": 0, "y": 0, "width": width, "height": height, "scale": scale},
    })
    return shot.get("data") or None
