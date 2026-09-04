"""What the Resident has been doing, read back out of the record.

The Tasks pane needs to say what is happening right now and what just
happened. It could be given its own store, updated as the turn runs -- and
then there would be two accounts of the same events, which would agree until
the day they did not. So there is no second account. Every tool call and
every tool result is already written into the conversation as it happens;
this reads those rows back and pairs them up.

That pairing is where the honesty is. A call with a result is finished, and
the exit code says how. A call with no result is unfinished, and there are
two quite different reasons for that: the command is still running, or the
turn ended without it ever completing -- stopped by the owner, or lost when
the process went away. Those are not the same thing and the pane must not
render them the same way. An entry that sits at "running" forever because
AWORG never noticed it had died is precisely the kind of quiet lie this
interface exists not to tell.
"""

from __future__ import annotations

import json
from typing import Any

#: How many entries the pane keeps. Enough to see the shape of what a turn
#: did without turning the pane into a second transcript.
RECENT = 12

#: How much of a command to show on the entry's face. The whole of it is in
#: the detail line; this is what has to stay readable in a narrow pane.
SUMMARY_CHARS = 120


def _summarise(name: str, arguments: dict[str, Any]) -> str:
    """The one line that says what this call was.

    For a shell command that is the command itself -- nothing describes
    running `npm install` as well as the words `npm install`. Anything else
    falls back to naming the tool and its arguments, which is worse but
    honest, and stops a new tool from rendering as a blank row.
    """
    if isinstance(arguments, dict):
        command = arguments.get("command")
        if isinstance(command, str) and command.strip():
            line = " ".join(command.split())
            if len(line) > SUMMARY_CHARS:
                line = line[: SUMMARY_CHARS - 1] + "…"
            return line
        if arguments:
            rendered = json.dumps(arguments)[:SUMMARY_CHARS]
            return f"{name} {rendered}"
    return name


def _outcome(payload: dict[str, Any]) -> tuple[str, str]:
    """What a finished call's result amounts to, as state and detail."""
    observed = payload.get("observed") or {}
    failed = bool(payload.get("failed"))

    facts = []
    if "exit_code" in observed:
        facts.append(f"exit {observed['exit_code']}")
    if observed.get("duration_ms") is not None:
        facts.append(_duration(observed["duration_ms"]))
    if observed.get("error"):
        facts.append(str(observed["error"]).replace("_", " "))

    if not facts:
        facts.append("failed" if failed else "done")
    return ("failed" if failed else "ok"), ", ".join(facts)


def _duration(ms: Any) -> str:
    try:
        ms = int(ms)
    except (TypeError, ValueError):
        return ""
    if ms < 1000:
        return f"{ms} ms"
    if ms < 60_000:
        return f"{ms / 1000:.1f} s"
    return f"{ms // 60000}m {(ms % 60000) // 1000}s"


def recent(rows: list[dict[str, Any]], active: bool) -> list[dict[str, Any]]:
    """The last few tool calls, paired with what came of them.

    `active` is whether a turn is actually in flight. It is the only thing
    that separates a call still running from one that never finished, and it
    is a fact about the process rather than about the record -- which is why
    it has to be passed in rather than inferred from the rows.
    """
    calls: list[dict[str, Any]] = []
    index: dict[str, dict[str, Any]] = {}

    for row in rows:
        role, content = row["role"], row["content"]
        if role not in ("tool_call", "tool_result"):
            continue
        try:
            payload = json.loads(content)
        except (ValueError, TypeError):
            continue

        if role == "tool_call":
            for call in payload.get("calls") or []:
                entry = {
                    "id": call.get("id") or "",
                    "name": call.get("name") or "tool",
                    "summary": _summarise(call.get("name") or "tool",
                                          call.get("arguments") or {}),
                    "detail": "",
                    "state": "running",
                    "at": row.get("created_at"),
                }
                calls.append(entry)
                if entry["id"]:
                    index[entry["id"]] = entry
        else:
            entry = index.get(payload.get("id") or "")
            if entry is None:
                continue
            entry["state"], entry["detail"] = _outcome(payload)

    # Only the newest call can still be running; anything older that never
    # got a result was left behind when its turn ended.
    for position, entry in enumerate(calls):
        if entry["state"] != "running":
            continue
        last = position == len(calls) - 1
        if active and last:
            entry["detail"] = "running now"
        else:
            entry["state"] = "abandoned"
            entry["detail"] = "never finished"

    return list(reversed(calls[-RECENT:]))
