"""Make an HTTP request.

Mostly here so the Resident can check whether something it started is
answering, and reach an API without going through a shell and a curl that
may not be installed.
"""

from __future__ import annotations

import json as jsonlib

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

    text = response.text
    # Pretty-print JSON. A model reading a minified API response wastes
    # attention on the shape rather than the content, and the small ones
    # this is built for do that worst.
    content_type = response.headers.get("content-type", "")
    if "json" in content_type:
        try:
            text = jsonlib.dumps(response.json(), indent=2)
        except ValueError:
            pass

    head = f"{response.status_code} {response.reason_phrase}"
    body_text = text.strip() or "(empty response body)"

    return ToolResult(
        text=size_for_model(f"{head}\n\n{body_text}"),
        payload=text,
        is_error=response.status_code >= 400,
        summary=head,
    )
