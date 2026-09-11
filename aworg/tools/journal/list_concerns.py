"""What went wrong and has not been dealt with."""

from __future__ import annotations

from ..base import ToolContext, ToolError, ToolResult


NAME = "list_concerns"

DESCRIPTION = (
    "See what is still outstanding in the Living Log: the failures and "
    "alarms nobody has closed out. Use it when you pick up work after a "
    "break, when the owner asks what is wrong, or before you report that "
    "everything is well. Each one carries an id you can resolve it by."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "limit": {
            "type": "integer",
            "description": "How many to show. The default is usually right.",
        },
    },
}

#: How much of an entry's detail to show per line. The full text is often a
#: stack trace or a build log, and a list that prints them whole is a list
#: nobody can read -- which is the failure this whole pane is vulnerable to.
#: Enough to recognise the thing, not enough to drown the rest.
DETAIL_CHARS = 220


async def run(context: ToolContext, limit: int = 25) -> ToolResult:
    journal = getattr(context, "journal", None)
    if journal is None:
        raise ToolError("The Living Log is not wired up in this Aworg.")

    try:
        limit = max(1, min(int(limit), 100))
    except (TypeError, ValueError):
        limit = 25

    entries = journal.open_entries(limit=limit)
    if not entries:
        # Said plainly rather than as an empty list. "Nothing is outstanding"
        # is a real and useful answer, and a tool that returns nothing at all
        # invites the reader to assume it failed to look.
        return ToolResult(
            text="Nothing is outstanding. The Living Log has no open concerns.",
            summary="nothing open",
        )

    lines = []
    for entry in entries:
        detail = " ".join((entry.get("detail") or "").split())
        if len(detail) > DETAIL_CHARS:
            detail = detail[:DETAIL_CHARS].rstrip() + "…"
        lines.append(
            f"#{entry['id']}  [{entry['level']}] {entry['at']}  "
            f"{entry.get('source') or 'aworg'}: {entry['summary']}"
            + (f"\n      {detail}" if detail else "")
        )

    count = len(entries)
    return ToolResult(
        text=(
            f"{count} open concern{'s' if count != 1 else ''}:\n\n"
            + "\n".join(lines)
            + "\n\nResolve one with resolve_concern once you have dealt with "
            "it -- or, if it turns out not to have been trouble at all, say "
            "that. An entry nobody ever closes is one nobody reads."
        ),
        summary=f"{count} open",
    )
