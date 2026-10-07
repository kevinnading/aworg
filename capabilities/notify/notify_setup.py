"""Show, or change, where this Aworg's notifications go."""

from __future__ import annotations

import re

from aworg.tools.base import ToolContext, ToolError, ToolResult

from ._topic import load, save, subscribe_text

NAME = "notify_setup"

DESCRIPTION = (
    "Show the ntfy topic this Aworg sends notifications to and how the owner "
    "subscribes to it. Give a topic or server to change them, for example to "
    "an ntfy server the owner runs."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "topic": {
            "type": "string",
            "description": "A new topic name: letters, digits, - and _, at most 64.",
        },
        "server": {
            "type": "string",
            "description": "A different ntfy server address. Defaults to https://ntfy.sh.",
        },
    },
}


async def run(context: ToolContext, topic: str = "", server: str = "") -> ToolResult:
    data, _ = load()
    changed = []
    if topic:
        topic = str(topic).strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", topic):
            raise ToolError("A topic is 1-64 letters, digits, '-' or '_'.")
        data["topic"] = topic
        changed.append("topic")
    if server:
        server = str(server).strip().rstrip("/")
        if not server.startswith(("http://", "https://")):
            raise ToolError("The server must be an http:// or https:// address.")
        data["server"] = server
        changed.append("server")
    if changed:
        save(data)
    head = f"Changed the {' and '.join(changed)}. " if changed else ""
    return ToolResult(
        text=f"{head}Notifications go to topic {data['topic']} on {data['server']}. {subscribe_text(data)}",
        summary=data["topic"],
    )
