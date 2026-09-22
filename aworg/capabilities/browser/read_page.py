"""Read the page that is already open, whole or in part."""

from __future__ import annotations

from aworg.tools.base import ToolContext, ToolError, ToolResult

from ._cdp import BrowserError, browser
from ._page import TEXT_LIMIT, describe, extract, summary


NAME = "read_page"

DESCRIPTION = (
    "Read the page that is currently open, without loading it again. Give a "
    "CSS selector to read one part of it, or nothing to read the whole page. "
    "Use this after page_do, or to look again at a page that updates itself."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "selector": {
            "type": "string",
            "description": (
                "A CSS selector, to read just that part -- '#results', "
                "'.error', 'table'. Leave it out for the whole page."
            ),
        },
        "html": {
            "type": "boolean",
            "description": (
                "Return the HTML of the selected part rather than its text. "
                "Only useful when you need the markup itself."
            ),
        },
    },
}

#: Markup is far bulkier than text for the same information, so it is held to
#: a tighter limit. A Resident that needs more than this of the raw HTML
#: wants a narrower selector, not a bigger budget.
HTML_LIMIT = 4000


async def run(
    context: ToolContext,
    selector: str | None = None,
    html: bool = False,
) -> ToolResult:
    try:
        page_browser = await browser(start_if_needed=False)

        if selector:
            # Passed as an argument rather than spliced into the expression,
            # so that a selector containing a quote is a selector rather
            # than a way to write JavaScript.
            # A form field's contents are a property rather than text or
            # markup, so a field read as either comes back empty -- which is
            # exactly the case a Resident is checking when it reads one.
            found = await page_browser.evaluate(
                "(() => { const el = document.querySelector("
                + _as_js_string(selector)
                + "); if (!el) return null; const value = (el.value ?? null);"
                " return { html: el.outerHTML,"
                " text: (el.innerText || el.textContent || ''), value }; })()"
            )
            if not found:
                raise ToolError(
                    f"Nothing on this page matches {selector!r}. "
                    "Use read_page without a selector to see what is there."
                )
            body = found["html"] if html else found["text"]
            if found.get("value") is not None:
                body = f"value: {found['value']}" + ("\n" + body if body else "")
            limit = HTML_LIMIT if html else TEXT_LIMIT
            clipped = len(body) > limit
            text = body[:limit].rstrip() + (
                f"\n... [first {limit} characters]" if clipped else ""
            )
            return ToolResult(
                text=f"{selector} on {page_browser.url}\n\n{text}",
                payload=found,
                summary=f"{selector}, {len(body)} chars",
            )

        page = await extract(page_browser)
    except BrowserError as exc:
        raise ToolError(str(exc)) from exc

    return ToolResult(
        text=describe(page_browser, page),
        payload=page,
        summary=summary(page_browser, page),
    )


def _as_js_string(value: str) -> str:
    """A Python string as a JavaScript literal, safely.

    JSON's string syntax is a subset of JavaScript's, which makes json.dumps
    the correct escaper here rather than quoting by hand.
    """
    import json

    return json.dumps(value)
