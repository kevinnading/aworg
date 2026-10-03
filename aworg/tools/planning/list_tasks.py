"""Read the plan back in full.

The Resident already sees a compact view of its open tasks in every system
prompt, so this is for the times that view is not enough: checking what was
finished, re-reading the detail of something written long ago, or finding
the id of a task to update.
"""

from __future__ import annotations

from ..base import ToolContext, ToolError, ToolResult, size_for_model


NAME = "list_tasks"

DESCRIPTION = (
    "Read your plan in full, with each task's detail and id. Open tasks are "
    "already in your prompt."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "state": {
            "type": "string",
            "enum": ["open", "pending", "active", "blocked", "done", "abandoned", "all"],
            "description": "Which tasks to show. Defaults to open ones.",
        },
    },
    "required": [],
}


async def run(context: ToolContext, state: str = "open") -> ToolResult:
    store = getattr(context, "store", None)
    if store is None:
        raise ToolError("Task keeping is not wired up in this Aworg.")

    wanted = str(state or "open").strip().lower()
    if wanted == "all":
        states = None
    elif wanted == "open":
        states = store.OPEN_STATES
    elif wanted in store.TASK_STATES:
        states = (wanted,)
    else:
        raise ToolError(f"{state!r} is not a task state or 'open' or 'all'.")

    tasks = store.list_tasks(states)
    if not tasks:
        return ToolResult(
            text=(
                "Your plan is empty."
                if wanted in ("open", "all")
                else f"No tasks are {wanted}."
            ),
            summary="none",
        )

    by_id = {t["id"]: t for t in tasks}
    lines = []
    for entry in tasks:
        # Subtasks sit under their parent where the parent is in view, and
        # stand on their own where it is not -- a task should never be
        # invisible because of how it was filtered.
        lead = "  " if entry["parent_id"] in by_id else ""
        lines.append(f"{lead}[{entry['state']}] {entry['id']}  {entry['title']}")
        if entry["detail"]:
            lines.append(f"{lead}    {entry['detail']}")
        if entry["note"]:
            lines.append(f"{lead}    note: {entry['note']}")

    return ToolResult(
        text=size_for_model("\n".join(lines), context.result_limit),
        payload="\n".join(lines),
        summary=f"{len(tasks)} task{'s' if len(tasks) != 1 else ''}",
    )
