"""Move one task along, and say what happened to it."""

from __future__ import annotations

from ..base import ToolContext, ToolError, ToolResult


NAME = "update_task"

DESCRIPTION = "Change a task's state, note or detail."

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "task": {"type": "string", "description": "The task id."},
        "state": {
            "type": "string",
            "enum": ["pending", "active", "blocked", "done", "abandoned"],
            "description": (
                "active = working on it now. done = finished. blocked = "
                "cannot proceed. abandoned = no longer worth doing."
            ),
        },
        "note": {
            "type": "string",
            "description": (
                "What happened. Required when blocking or abandoning."
            ),
        },
        "detail": {
            "type": "string",
            "description": "Replace the task's detail, if you have learned more.",
        },
    },
    "required": ["task", "state"],
}

#: States where an unexplained change is worse than useless. "Blocked" with
#: no reason tells the next reader -- which may be this Resident tomorrow --
#: exactly nothing, and abandoning silently is how a plan quietly lies about
#: what it achieved.
NEEDS_REASON = ("blocked", "abandoned")

#: The states worth a Living Log entry. Endings only -- a task becoming
#: `active` is the Resident picking up the next thing, which is what
#: Activities is for.
ENDINGS = ("done", "blocked", "abandoned")


async def run(
    context: ToolContext,
    task: str = "",
    state: str = "",
    note: str = "",
    detail: str = "",
) -> ToolResult:
    store = getattr(context, "store", None)
    if store is None:
        raise ToolError("Task keeping is not wired up in this Aworg.")

    existing = store.get_task(str(task).strip())
    if existing is None:
        open_now = store.list_tasks(store.OPEN_STATES, limit=10)
        listing = "\n".join(f"  {t['id']}  {t['title']}" for t in open_now)
        raise ToolError(
            f"There is no task with id {task!r}."
            + (f" Open tasks:\n{listing}" if listing else " Your plan is empty.")
        )

    state = str(state).strip().lower()
    if state not in store.TASK_STATES:
        raise ToolError(
            f"{state!r} is not a task state. Use one of: "
            f"{', '.join(store.TASK_STATES)}."
        )
    if state in NEEDS_REASON and not str(note).strip():
        raise ToolError(
            f"Marking a task {state} needs a note saying why."
        )

    updated = store.update_task(
        existing["id"], state=state, note=note or None, detail=detail or None
    )
    remaining = len(store.list_tasks(store.OPEN_STATES))

    # Only the endings. A task moving to `active` is the Resident picking up
    # the next thing and belongs in Activities, not here; a task that ended
    # -- and especially one that ended badly -- is what an owner reading
    # back wants to find. `blocked` and `abandoned` carry a reason by the
    # rule above, so the entry always says why.
    if getattr(context, "journal", None) is not None and state in ENDINGS:
        context.journal.record(
            f"{updated['title']} is {state}",
            level="note" if state == "done" else "concern",
            kind="task",
            source=context.source,
            detail=updated["note"] or "",
        )

    return ToolResult(
        text=(
            f"{updated['title']} is now {state}."
            + (f" Note: {updated['note']}" if updated["note"] else "")
            + f"\n{remaining} task{'s' if remaining != 1 else ''} still open."
        ),
        summary=f"{updated['title'][:28]} -> {state}",
    )
