"""Make an HTTP request.

Mostly here so the Resident can check whether something it started is
answering, and reach an API without going through a shell and a curl that
may not be installed.
"""

from __future__ import annotations

import json as jsonlib
import re
from html import unescape

import httpx

from ..base import ToolContext, ToolError, ToolResult, size_for_model


NAME = "http_request"

DESCRIPTION = (
    "Make an HTTP request and return the status and response body. Useful "
    "for calling an API, or checking whether a running service answers."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "description": "The full URL, including http:// or https://.",
        },
        "method": {
            "type": "string",
            "description": "GET, POST, PUT, PATCH, DELETE or HEAD. Defaults to GET.",
        },
        "headers": {
            "type": "object",
            "description": "Header names and values to send.",
        },
        "body": {
            "type": "string",
            "description": "Request body, for POST and the like.",
        },
        "timeout": {
            "type": "integer",
            "description": "Seconds to wait. Defaults to 30.",
        },
    },
    "required": ["url"],
}

METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
DEFAULT_TIMEOUT = 30
MAX_TIMEOUT = 300


async def run(
    context: ToolContext,
    url: str,
    method: str = "GET",
    headers: dict | None = None,
    body: str = "",
    timeout: int = DEFAULT_TIMEOUT,
) -> ToolResult:
    verb = (method or "GET").upper()
    if verb not in METHODS:
        raise ToolError(f"{verb} is not a method this tool sends. Use one of: {', '.join(sorted(METHODS))}.")

    if not url.lower().startswith(("http://", "https://")):
        # Guessing the scheme would silently turn a request the model meant
        # to make securely into a plaintext one.
        raise ToolError(
            f"{url!r} needs to start with http:// or https://."
        )

    seconds = max(1, min(int(timeout or DEFAULT_TIMEOUT), MAX_TIMEOUT))
    context.progress(detail=f"{verb} {url[:60]}")

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=seconds) as client:
            response = await client.request(
                verb,
                url,
                headers=headers or None,
                content=body.encode("utf-8") if body else None,
            )
    except httpx.TimeoutException:
        raise ToolError(f"{url} did not answer within {seconds} seconds.") from None
    except httpx.RequestError as exc:
        raise ToolError(f"{url} could not be reached: {exc}.") from None

    raw = response.text
    content_type = response.headers.get("content-type", "")

    # Pretty-print JSON. A model reading a minified API response wastes
    # attention on the shape rather than the content, and the small ones
    # this is built for do that worst.
    text = raw
    if "json" in content_type:
        try:
            text = jsonlib.dumps(response.json(), indent=2)
        except ValueError:
            pass
    elif _is_html(content_type, raw):
        # **A web page is not its markup.**
        #
        # Fetching a page for research and putting the document into the
        # conversation is the most expensive thing a Resident can do, and
        # almost none of it is what it went to read. Four pages fetched in
        # one session came to 175,000 tokens -- one of them 71,000 alone --
        # against 855 tokens of everything the Resident actually said. The
        # conversation was 99.5% markup, and every later request in that
        # session carried all of it again.
        #
        # So scripts, styles and tags come out, and the readable content goes
        # to the model. The whole document stays as the payload, so an owner
        # opening the Activity sees exactly what came back: it is kept out of
        # the context window, not hidden.
        text = _readable(raw)

    head = f"{response.status_code} {response.reason_phrase}"
    body_text = text.strip() or "(empty response body)"
    note = ""
    if len(text) < len(raw):
        # Said rather than done quietly, the same rule size_for_model
        # follows: a model reading an extract should know it is one.
        note = (
            f" -- {len(raw):,} characters of markup read as "
            f"{len(text):,} of text"
        )

    return ToolResult(
        text=size_for_model(f"{head}{note}\n\n{body_text}", context.result_limit),
        payload=raw,
        is_error=response.status_code >= 400,
        summary=head,
    )


def _is_html(content_type: str, raw: str) -> bool:
    """Whether this is a document rather than data.

    The header first, and the opening bytes when a server did not say --
    plenty serve HTML as text/plain, and guessing wrong in that direction
    costs an unread page rather than a broken one.
    """
    if "html" in content_type or "xml" in content_type:
        return True
    if content_type and "text/plain" not in content_type:
        return False
    start = raw[:400].lstrip().lower()
    return start.startswith(("<!doctype html", "<html")) or "<body" in start


#: Elements whose contents are not reading matter, however much of the file
#: they take up. On a modern page these are most of it.
_DROPPED = ("script", "style", "noscript", "template", "svg", "head")


def _readable(raw: str) -> str:
    """The words on a page, without the machinery around them.

    Deliberately a little regular expression rather than a parser. AWORG has
    three dependencies and this is not worth a fourth: the job is to keep a
    megabyte of markup out of a context window, not to render the page
    faithfully, and the real document stays on the Activity for anyone who
    needs it.
    """
    text = raw
    for tag in _DROPPED:
        text = re.sub(rf"<{tag}\b.*?</{tag}\s*>", " ", text, flags=re.S | re.I)
    # Block-level tags become line breaks, so the text does not run together
    # into a single paragraph -- which is what makes an extract unreadable.
    text = re.sub(r"</(p|div|li|h[1-6]|tr|section|article)\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<br\b[^>]*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return "\n".join(line.strip() for line in text.splitlines()).strip()
