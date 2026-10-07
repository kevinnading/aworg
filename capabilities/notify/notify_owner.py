"""Push a notification to the owner through ntfy."""

from __future__ import annotations

import httpx

from aworg.tools.base import ToolContext, ToolError, ToolResult

from ._topic import load, subscribe_text

NAME = "notify_owner"

DESCRIPTION = (
    "Send the owner a push notification on their phone or desktop. It "
    "reaches them only once they have subscribed to this Aworg's topic; "
    "notify_setup gives the topic and how to subscribe."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "message": {"type": "string", "description": "The notification text."},
        "title": {"type": "string", "description": "A short title. Optional."},
        "priority": {
            "type": "integer",
            "description": "1 (min) to 5 (urgent). Defaults to 3; 4 and 5 make a louder alert.",
        },
        "link": {
            "type": "string",
            "description": "An address opened when the notification is tapped. Optional.",
        },
    },
    "required": ["message"],
}


async def run(
    context: ToolContext,
    message: str = "",
    title: str = "",
    priority: int = 3,
    link: str = "",
) -> ToolResult:
    if not str(message).strip():
        raise ToolError("No message was given.")
    data, new = load()
    try:
        level = max(1, min(5, int(priority or 3)))
    except (TypeError, ValueError):
        level = 3

    headers = {"Priority": str(level)}
    if title:
        headers["Title"] = str(title).strip()
    if link:
        headers["Click"] = str(link).strip()
    url = f"{data['server'].rstrip('/')}/{data['topic']}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(url, content=str(message).encode("utf-8"), headers=headers)
    except httpx.HTTPError as exc:
        raise ToolError(f"Could not reach {data['server']}: {exc}") from None
    if response.status_code >= 400:
        raise ToolError(f"{data['server']} refused the notification: HTTP {response.status_code} {response.text[:200]}")

    text = f"Sent to topic {data['topic']}."
    if new:
        text += " This topic was just created, so nobody is subscribed yet. " + subscribe_text(data)
    return ToolResult(text=text, summary=f"sent to {data['topic']}")
