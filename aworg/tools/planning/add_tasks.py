"""Write down a plan, so that it outlives the conversation that produced it.

This is the tool that makes long work possible at all.

A context window is a hard edge and history only grows, so the oldest
messages stop being sent -- in a real session on a 9B, twenty-six of
forty-five messages were already invisible to the model. Anything the
Resident only "remembers" by having said it earlier is therefore forgotten,
and a plan made in message three is gone by message eighty.

Tasks are the memory that is not conversation. They survive truncation, and
they survive a restart, which is the difference between a Resident that does
one thing well and a Resident that finishes something large.
"""

from __future__ import annotations

from ..base import ToolContext, ToolError, ToolResult


NAME = "add_tasks"

DESCRIPTION = (
    "Write down what you intend to do, as a list of tasks. Use this before "
    "starting anything that takes more than a couple of steps, and add to it "
    "whenever you discover work you had not planned for. Your plan survives "
    "even when this conversation no longer fits in your context."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "tasks": {
            "type": "array",
            "description": "The tasks to add, in the order you mean to do them.",
            "items": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "One short line naming the task.",
                    },
                    "detail": {
                        "type": "string",
                        "description": (
                            "Everything needed to do this later, written for "
                            "a reader who was not present: exact paths, exact "
                            "requirements. You may be picking this up when "
                            "the conversation that produced it is gone."
                        ),
                    },
                    "parent": {
                        "type": "string",
                        "description": "Task id this is a subtask of. Optional.",
                    },
                },
                "required": ["title"],
            },
        },
    },
    "required": ["tasks"],
}

#: A guard against a model that has decided to enumerate the universe. A plan
#: longer than this is not a plan, and it would crowd out the context the
#: Resident needs to actually do any of it.
MAX_AT_ONCE = 25


async def run(context: ToolContext, tasks: list | None = None) -> ToolResult:
    store = getattr(context, "store", None)
    if store is None:
        raise ToolError("Task keeping is not wired up in this Aworg.")

    if isinstance(tasks, dict):
        # A model that sent one task rather than a list of one. Cheap to
        # accept, and refusing would cost a round to learn nothing.
        tasks = [tasks]
    if not tasks:
        raise ToolError("No tasks were given. Say what you intend to do.")
    if len(tasks) > MAX_AT_ONCE:
        raise ToolError(
            f"That is {len(tasks)} tasks at once, and the limit is "
            f"{MAX_AT_ONCE}. Add the next few steps rather than the whole "
            "project, and add more as you get there."
        )

    prepared = []
    for entry in tasks:
        if isinstance(entry, str):
            entry = {"title": entry}
        if not isinstance(entry, dict):
            continue
        prepared.append(
            {
                "title": entry.get("title") or entry.get("name") or "",
                "detail": entry.get("detail") or entry.get("description") or "",
                "parent_id": entry.get("parent") or entry.get("parent_id"),
            }
        )

    if not prepared:
        raise ToolError("None of those entries had a title.")

    created = store.add_tasks(prepared)
    lines = "\n".join(f"  {t['id']}  {t['title']}" for t in created)
    return ToolResult(
        text=(
            f"Added {len(created)} task{'s' if len(created) != 1 else ''} to "
            f"your plan:\n{lines}\n\nMark one active with update_task when you "
            "start it, and done when you have watched it succeed."
        ),
        summary=f"+{len(created)} task{'s' if len(created) != 1 else ''}",
    )
