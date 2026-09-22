"""Take a picture of the open page -- and look at it.

Two things at once, on purpose. The PNG goes to the Living Workspace at full
size, because that one is for the owner: it is what gets shown, attached, or
compared against later. A second, smaller JPEG comes back attached to the
result, because that one is for the Resident, and a model reading a
four-megabyte screenshot pays for every pixel of a resolution it cannot use.

Looking costs real tokens -- roughly a thousand per picture, every time the
conversation is sent afterwards -- so `only_save` exists for the case where
the owner wants a file and the Resident has no need to see the page. It is a
negative on purpose. The first version had a `show` that defaulted to true,
and asked to screenshot a page and say what it looked like, the Resident
turned it off and then described the page from what it already knew about
that site: plausible, unverified, and the exact failure this capability
exists to remove.

Reading the page with read_page is still cheaper and more precise for
anything made of words. What a picture is for is the question words cannot
answer: whether it looks right.
"""

from __future__ import annotations

import base64
from datetime import datetime

from aworg.tools.base import ToolContext, ToolError, ToolResult, resolve_path

from ._cdp import BrowserError, browser


NAME = "screenshot"

DESCRIPTION = (
    "Take a picture of the page that is open. It is saved as a PNG in the "
    "Living Workspace and you are shown it, so this is how you find out "
    "what a page actually looks like -- layout, spacing, whether something "
    "renders correctly. Pass for_owner when the owner asked to see it, "
    "which puts it in the chat rather than folded away. Never describe how "
    "a page looks from a screenshot you did not see; for what a page says "
    "rather than how it looks, read_page is cheaper and more exact."
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
        "for_owner": {
            "type": "boolean",
            "description": (
                "Put the picture in the chat where the owner will see it "
                "straight away. Use it when they asked to see something. "
                "Leave it off when you are checking your own work -- those "
                "are still there, folded away with the other results."
            ),
        },
        "only_save": {
            "type": "boolean",
            "description": (
                "Save the file without showing it to you. Defaults to false. "
                "Only for when the owner asked for a file and you have no "
                "need to see the page yourself -- with this on you will not "
                "have seen it, and must not describe it."
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
    only_save: bool = False,
    for_owner: bool = False,
) -> ToolResult:
    try:
        page_browser = await browser(start_if_needed=False)
        keep = await page_browser.command("Page.captureScreenshot", {
            "format": "png",
            "captureBeyondViewport": bool(full_page),
        })
        look = None if only_save else await _for_the_model(page_browser, full_page)
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
        f"You have not seen this page. The picture was saved to {destination} "
        f"({size // 1024} KB) for the owner and not shown to you, because you "
        f"asked for only_save. Do not describe what it looks like; call "
        f"screenshot again without only_save if you need to see it."
    )

    return ToolResult(
        text=told,
        payload={"path": str(destination), "bytes": size, "url": page_browser.url},
        summary=f"{size // 1024} KB png" + (", looked" if look else ", unseen"),
        images=(
            [{"media_type": "image/jpeg", "data": look,
              "for_owner": bool(for_owner)}]
            if look else []
        ),
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
