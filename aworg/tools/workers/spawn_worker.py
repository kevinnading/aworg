"""Start a worker. See aworg/workers.py for what a worker is."""

from __future__ import annotations

from ..base import ToolContext, ToolError, ToolResult


NAME = "spawn_worker"

#: Describes itself at discovery, because its connection list is the owner's
#: and changes without any code changing. See describe_for.
DYNAMIC = True

DESCRIPTION = (
    "Start a worker: a separate model run with its own context, working in "
    "the background. It knows only what you give it here -- nothing about "
    "this machine, the workspace or this conversation, so the environment "
    "details its job needs go in the task. Returns its id at once; you are "
    "told when it finishes."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": "A short label, shown to the owner in the Workers pane.",
        },
        "task": {
            "type": "string",
            "description": "Its first message: the job, and whatever it needs to know.",
        },
        "instructions": {
            "type": "string",
            "description": "Its system prompt. Optional.",
        },
        "tools": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Names of the tools it may use, from your own list. It gets "
                "only these, and never the worker tools."
            ),
        },
        "skills": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Skills whose full text goes into its system prompt.",
        },
        "connection": {
            "type": "string",
            "description": "Which model it runs on. Defaults to yours.",
        },
    },
    "required": ["task", "tools"],
}


async def run(
    context: ToolContext,
    task: str = "",
    name: str = "",
    instructions: str = "",
    tools: list | None = None,
    skills: list | None = None,
    connection: str = "",
) -> ToolResult:
    pool = getattr(context, "workers", None)
    if pool is None:
        raise ToolError("Workers are not wired up in this Aworg.")
    if not str(task).strip():
        raise ToolError("No task was given.")
    if tools is None:
        raise ToolError("No tools were given: name the ones its job needs.")
    try:
        worker = pool.spawn(
            name=str(name).strip(),
            task=str(task),
            instructions=str(instructions or ""),
            tools=[str(t) for t in tools],
            skills=[str(s) for s in (skills or [])],
            connection=str(connection or ""),
        )
    except ValueError as exc:
        raise ToolError(str(exc)) from None
    return ToolResult(
        text=(
            f"Started worker {worker.id} ({worker.name}) on "
            f"{worker.connection['name']}. You will be told when it finishes."
        ),
        summary=f"{worker.name} on {worker.connection['name']}",
    )


def describe_for(connections: list[dict] | None = None, **_: object) -> dict:
    """The descriptor, with the usable connections as an enum and their tags."""
    if not connections:
        return {}
    listed = "\n".join(
        f"- {c['name']}: {c['model']}"
        + (f", tags: {', '.join(c['tags'])}" if c.get("tags") else "")
        + (f", {c['context']:,} token window" if c.get("context") else "")
        for c in connections
    )
    schema = {
        "type": "object",
        "properties": {
            **INPUT_SCHEMA["properties"],
            "connection": {
                "type": "string",
                "enum": [c["name"] for c in connections],
                "description": "Which model it runs on. Defaults to yours.",
            },
        },
        "required": ["task", "tools"],
    }
    return {
        "name": NAME,
        "description": f"{DESCRIPTION}\n\nConnections:\n{listed}",
        "inputSchema": schema,
    }
