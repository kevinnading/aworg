"""Move one task along, and say what happened to it."""

from __future__ import annotations

from ..base import ToolContext, ToolError, ToolResult


NAME = "update_task"

DESCRIPTION = (
    "Change a task's state as you work: active when you start it, done when "
    "you have watched it succeed, blocked when you genuinely cannot proceed. "
    "Never mark something done that you have not verified."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "task": {"type": "string", "description": "The task id."},
        "state": {
            "type": "string",
            "enum": ["pending", "active", "blocked", "done", "abandoned"],
            "description": (
                "active = working on it now. done = finished and verified. "
                "blocked = cannot proceed, say why in the note. abandoned = "
                "no longer worth doing."
            ),
        },
        "note": {
            "type": "string",
            "description": (
                "What happened, for whoever reads this later. Required when "
                "blocking or abandoning: a task that is stuck without a "
                "reason cannot be picked up by anyone."
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
            f"Marking a task {state} needs a note saying why. Whoever picks "
            "this up next was not here for the reason."
        )

    updated = store.update_task(
        existing["id"], state=state, note=note or None, detail=detail or None
    )
    remaining = len(store.list_tasks(store.OPEN_STATES))
    return ToolResult(
        text=(
            f"{updated['title']} is now {state}."
            + (f" Note: {updated['note']}" if updated["note"] else "")
            + f"\n{remaining} task{'s' if remaining != 1 else ''} still open."
        ),
        summary=f"{updated['title'][:28]} -> {state}",
    )
