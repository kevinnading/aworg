"""What the page asked the network for, and what came back.

The other half of debugging something you built. The console tells you what
the code complained about; this tells you what it actually fetched -- which
is where "the list is empty and nothing is on fire" gets explained, because
the request returned 200 with an empty array, or was never made at all.

Recorded for every page load whether or not anyone asks, because by the time
the question occurs to anyone the requests have been and gone. Reported only
when asked, because ninety asset fetches are not what most calls are about.
"""

from __future__ import annotations

from aworg.tools.base import ToolContext, ToolError, ToolResult

from ._cdp import BrowserError, browser


NAME = "page_requests"

DESCRIPTION = (
    "List what the open page fetched and what came back: method, URL, status,"
    " type and size. 'contains' narrows it to one endpoint, 'body' reads that"
    " response."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "contains": {
            "type": "string",
            "description": (
                "Only requests whose URL contains this. Use it to find one "
                "API call among the assets -- '/api/', 'tasks.json'."
            ),
        },
        "failed_only": {
            "type": "boolean",
            "description": (
                "Only the ones that failed or returned 400 and above."
            ),
        },
        "body": {
            "type": "boolean",
            "description": (
                "Also return the response body of the first match. Needs "
                "'contains' narrow enough to mean one request."
            ),
        },
    },
}

MAX_ROWS = 60
MAX_BODY = 5000


async def run(
    context: ToolContext,
    contains: str | None = None,
    failed_only: bool = False,
    body: bool = False,
) -> ToolResult:
    try:
        page_browser = await browser(start_if_needed=False)
    except BrowserError as exc:
        raise ToolError(str(exc)) from exc

    rows = list(page_browser.requests)
    if contains:
        rows = [r for r in rows if contains.lower() in (r["url"] or "").lower()]
    if failed_only:
        rows = [r for r in rows
                if r["error"] or (r["status"] or 0) >= 400]

    if not rows:
        # Said as three different facts, because they lead three different
        # ways: nothing matched, nothing failed, or nothing was recorded
        # because no page has been loaded since the browser started.
        if not page_browser.requests:
            raise ToolError(
                "Nothing has been requested since this page was opened. Load "
                "a page with open_page first."
            )
        raise ToolError(
            f"No request matches {contains!r}."
            if contains and not failed_only else
            "Nothing failed on this page."
            if failed_only else
            "No requests match."
        )

    lines = [f"{len(rows)} request(s) on {page_browser.url}", ""]
    for record in rows[:MAX_ROWS]:
        state = (
            f"FAILED {record['error']}" if record["error"]
            else str(record["status"] or "pending")
        )
        size = (
            f"{record['bytes'] / 1024:.1f} KB"
            if isinstance(record["bytes"], (int, float)) and record["bytes"]
            else ""
        )
        lines.append(
            f"  {state:<22} {record['method']:<5} {record['url'][:110]}"
            + (f"   {record['type']}" if record["type"] else "")
            + (f"  {size}" if size else "")
        )
    if len(rows) > MAX_ROWS:
        lines.append(f"  ... and {len(rows) - MAX_ROWS} more")

    payload = {"requests": rows[:MAX_ROWS]}
    if body:
        lines.append("")
        lines.append(await _body(page_browser, rows[0], payload))

    return ToolResult(
        text="\n".join(lines),
        payload=payload,
        summary=f"{len(rows)} request(s)",
    )


async def _body(page_browser, record, payload) -> str:
    """One response's content, if the browser still has it.

    Bodies are held by the renderer and dropped when it needs the memory, so
    this can fail for a perfectly ordinary request that happened a while
    ago. Saying so is better than an empty string that reads like an empty
    response -- which is the exact thing being investigated.
    """
    try:
        got = await page_browser.command(
            "Network.getResponseBody", {"requestId": record["id"]}
        )
    except BrowserError as exc:
        return f"The body of {record['url'][:80]} is no longer available: {exc}"

    content = got.get("body") or ""
    if got.get("base64Encoded"):
        return (
            f"{record['url'][:80]} returned {len(content)} characters of "
            "base64 -- it is not text."
        )
    payload["body"] = content[:MAX_BODY]
    clipped = len(content) > MAX_BODY
    return (
        f"Body of {record['url'][:80]}:\n"
        + content[:MAX_BODY]
        + (f"\n... [first {MAX_BODY} characters]" if clipped else "")
    )
