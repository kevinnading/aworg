"""Start a worker. See aworg/workers.py for what a worker is."""

from __future__ import annotations

from ..base import ToolContext, ToolError, ToolResult


NAME = "spawn_worker"

#: Describes itself at discovery, because its connection list is the owner's
#: and changes without any code changing. See describe_for.
DYNAMIC = True

DESCRIPTION = (
    "Start a worker: a separate model run with its own context, working in "
    "the background. It is given this machine's environment; it does not "
    "see this conversation, so everything else its job needs goes in the "
    "task. Returns its id at once. Its reply arrives as a message after your "
    "current reply ends."
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
                "The tools it may use, from your own. It sees these exactly "
                "as you see them, and no others."
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
    named = [str(t).strip() for t in (tools or []) if str(t).strip()]
    if not named:
        raise ToolError("No tools were given. Name the ones its job needs.")
    try:
        worker = pool.spawn(
            name=str(name).strip(),
            task=str(task),
            instructions=str(instructions or ""),
            tools=named,
            skills=[str(s) for s in (skills or [])],
            connection=str(connection or ""),
        )
    except ValueError as exc:
        raise ToolError(str(exc)) from None
    return ToolResult(
        text=(
            f"Started worker {worker.id} ({worker.name}) on "
            f"{worker.connection['name']} with {', '.join(named)}. Its reply "
            "arrives as a message after your current reply ends."
        ),
        summary=f"{worker.name} on {worker.connection['name']}",
    )


def describe_for(
    connections: list[dict] | None = None,
    grantable: list[str] | None = None,
    **_: object,
) -> dict:
    """The descriptor, with the usable connections and grantable tools as enums."""
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
            "tools": {
                **INPUT_SCHEMA["properties"]["tools"],
                "items": {"type": "string", "enum": list(grantable or [])},
                "minItems": 1,
            },
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
