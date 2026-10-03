"""Close out one thing that went wrong, with an account of what happened."""

from __future__ import annotations

from ..base import ToolContext, ToolError, ToolResult


NAME = "resolve_concern"

DESCRIPTION = (
    "Close one open concern in the Living Log, saying what was done about it."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "entry": {
            "type": "integer",
            "description": "The id from list_concerns, without the #.",
        },
        "resolution": {
            "type": "string",
            "description": (
                "What you fixed, how it recovered, or why it was never a "
                "problem."
            ),
        },
    },
    "required": ["entry", "resolution"],
}

#: The shortest account worth storing. Not a style rule -- "ok", "done" and
#: "fixed" are the three things a model reaches for when it is closing a
#: list rather than reporting on it, and every one of them leaves the next
#: reader knowing exactly what they knew before.
MIN_RESOLUTION = 12


async def run(context: ToolContext, entry: int = 0, resolution: str = "") -> ToolResult:
    journal = getattr(context, "journal", None)
    store = getattr(context, "store", None)
    if journal is None or store is None:
        raise ToolError("The Living Log is not wired up in this Aworg.")

    try:
        entry_id = int(entry)
    except (TypeError, ValueError):
        raise ToolError(
            f"{entry!r} is not an entry id. list_concerns shows them, as #12."
        ) from None

    existing = store.get_journal_entry(entry_id)
    if existing is None:
        raise ToolError(
            f"There is no Living Log entry #{entry_id}. "
            "Run list_concerns to see what is actually open."
        )

    # A note records something that happened; there is nothing to resolve
    # about it. Refused rather than quietly allowed, because a Resident
    # closing notes is one working through the log instead of the trouble.
    if existing["level"] not in store.OPEN_LEVELS:
        raise ToolError(
            f"Entry #{entry_id} is a {existing['level']}, not a concern. "
            "Notes record what happened and are not closed out."
        )

    if existing["resolved"]:
        by = existing["resolved_by"] or "somebody"
        raise ToolError(
            f"Entry #{entry_id} was already closed by {by}: "
            f"{existing['resolution'] or 'no account given'}"
        )

    account = " ".join(str(resolution).split())
    if len(account) < MIN_RESOLUTION:
        raise ToolError(
            f"A resolution of {account!r} is too short. Say what was fixed, "
            "how it recovered, or why it was never trouble."
        )

    closed = journal.resolve(entry_id, by=context.source, resolution=account)
    if closed is None:                                     # pragma: no cover
        raise ToolError(f"Could not close entry #{entry_id}.")

    remaining = len(journal.open_entries(limit=100))
    return ToolResult(
        text=(
            f"Closed #{entry_id}: {closed['summary']}.\n"
            f"{account}\n\n"
            + (
                f"{remaining} concern{'s' if remaining != 1 else ''} still open."
                if remaining
                else "Nothing is outstanding now."
            )
        ),
        summary=f"closed #{entry_id}",
    )
