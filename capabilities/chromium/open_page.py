"""Open a page in a real browser and read what it became."""

from __future__ import annotations

from aworg.tools.base import ToolContext, ToolError, ToolResult

from ._cdp import BrowserError, browser
from ._page import describe, extract, summary


NAME = "open_page"

DESCRIPTION = (
    "Open a URL in a real browser and read the page after its JavaScript has "
    "run. Use this rather than http_request whenever the page is an "
    "application rather than a document -- including anything you built "
    "yourself. Returns the page's text, its links and controls, and anything "
    "the console or the network complained about. The page stays open for "
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
    },
    "required": ["url"],
}

MAX_WAIT = 15


async def run(
    context: ToolContext,
    url: str,
    wait: float = 0.6,
    links: bool = True,
) -> ToolResult:
    url = (url or "").strip()
    if not url:
        raise ToolError("open_page needs a URL.")
    if "://" not in url:
        # A bare host is what a person types, and refusing it teaches the
        # model a rule rather than getting it the page.
        url = "http://" + url

    try:
        page_browser = await browser(processes=context.processes)
        if context.activity is not None:
            context.activity.progress = f"loading {url}"
        await page_browser.navigate(url, settle=max(0.0, min(float(wait), MAX_WAIT)))
        page = await extract(page_browser)
    except BrowserError as exc:
        raise ToolError(str(exc)) from exc

    return ToolResult(
        text=describe(page_browser, page, want_links=links),
        payload=page,
        summary=summary(page_browser, page),
    )
