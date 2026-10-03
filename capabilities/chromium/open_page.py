"""Open a page in a real browser and read what it became."""

from __future__ import annotations

from aworg.tools.base import ToolContext, ToolError, ToolResult

from ._cdp import BrowserError, browser
from ._page import describe, extract, summary


NAME = "open_page"

DESCRIPTION = (
    "Open a URL in a real browser and read the page after its JavaScript has "
    "run. Returns the page's text, its links and controls, and anything the "
    "console or the network complained about. The page stays open for "
    "read_page, page_do and screenshot."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "description": "The full URL, including http:// or https://.",
        },
        "wait": {
            "type": "number",
            "description": (
                "Extra seconds to wait after the page loads, for content that "
                "arrives late. Defaults to 0.6, maximum 15."
            ),
        },
        "links": {
            "type": "boolean",
            "description": (
                "Include the list of links and controls. Defaults to true; "
                "turn it off when you only want the words."
            ),
        },
        "screen": {
            "type": "string",
            "description": (
                "Screen to open it on: 'phone' (390x844, touch), 'tablet' "
                "(820x1180, touch) or 'desktop' (1280x900, the default)."
            ),
        },
        "width": {
            "type": "integer",
            "description": (
                "An exact viewport width in pixels, instead of 'screen'."
            ),
        },
        "height": {
            "type": "integer",
            "description": "An exact viewport height in pixels.",
        },
        "dark": {
            "type": "boolean",
            "description": (
                "Open it as a visitor whose system is set to dark mode, so a "
                "page with a prefers-color-scheme rule shows its other face."
            ),
        },
    },
    "required": ["url"],
}

#: The two that are worth a name. Not a device list: this is a viewport and a
#: touch flag, not an iPhone, and pretending otherwise would have AWORG
#: maintaining a table of somebody else's hardware.
SCREENS = {
    "phone": (390, 844, True),
    "mobile": (390, 844, True),
    "tablet": (820, 1180, True),
    "desktop": (1280, 900, False),
}

MAX_WAIT = 15


async def run(
    context: ToolContext,
    url: str,
    wait: float = 0.6,
    links: bool = True,
    screen: str | None = None,
    width: int | None = None,
    height: int | None = None,
    dark: bool | None = None,
) -> ToolResult:
    url = (url or "").strip()
    if not url:
        raise ToolError("open_page needs a URL.")
    if "://" not in url:
        # A bare host is what a person types, and refusing it teaches the
        # model a rule rather than getting it the page.
        url = "http://" + url

    named = SCREENS.get((screen or "").strip().lower()) if screen else None
    if screen and named is None:
        raise ToolError(
            f"{screen!r} is not a screen this knows. It knows "
            + ", ".join(sorted(SCREENS))
            + " -- or give width and height."
        )

    try:
        page_browser = await browser(processes=context.processes)
        # Set before navigating, so the page lays out at the size it is
        # being asked about rather than reflowing into it afterwards.
        if named or width or height or dark is not None:
            await page_browser.emulate(
                width=width or (named[0] if named else None),
                height=height or (named[1] if named else None),
                mobile=bool(named[2]) if named else False,
                dark=dark,
            )
        if context.activity is not None:
            context.activity.progress = f"loading {url}"
        await page_browser.navigate(url, settle=max(0.0, min(float(wait), MAX_WAIT)))
        page = await extract(page_browser)
    except BrowserError as exc:
        raise ToolError(str(exc)) from exc

    how = ""
    if named or width or height:
        size = f"{width or (named[0] if named else 1280)}" \
               f"x{height or (named[1] if named else 900)}"
        how = f"[{screen or 'custom'} viewport, {size}]"
    if dark is not None:
        how = (how + " " if how else "") + f"[prefers-color-scheme: " \
              f"{'dark' if dark else 'light'}]"

    return ToolResult(
        text=(f"{how}\n" if how else "")
        + describe(page_browser, page, want_links=links),
        payload=page,
        summary=summary(page_browser, page),
    )
