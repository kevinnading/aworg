"""Where notifications go: an ntfy server and a topic, kept in this folder.

The topic is made up at random the first time it is needed. On ntfy anyone
who knows a topic can read it, so a long random one is what keeps the
owner's notifications theirs.
"""

from __future__ import annotations

import json
import secrets
from pathlib import Path

SETTINGS = Path(__file__).parent / "notify.json"
DEFAULT_SERVER = "https://ntfy.sh"


def load() -> tuple[dict, bool]:
    """The settings, and whether they were just created."""
    try:
        data = json.loads(SETTINGS.read_text(encoding="utf-8"))
        if data.get("topic") and data.get("server"):
            return data, False
    except (OSError, ValueError):
        pass
    data = {"server": DEFAULT_SERVER, "topic": "aworg-" + secrets.token_hex(8)}
    save(data)
    return data, True


def save(data: dict) -> None:
    SETTINGS.write_text(json.dumps(data, indent=2), encoding="utf-8")


def subscribe_text(data: dict) -> str:
    server = data["server"].rstrip("/")
    return (
        f"To receive them, the owner subscribes to topic {data['topic']} on "
        f"{server}: install the ntfy app (Android, iOS) and add that topic, "
        f"or open {server}/{data['topic']} in a browser and allow "
        "notifications."
    )
