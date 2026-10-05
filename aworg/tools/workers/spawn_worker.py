"""Start a worker. See aworg/workers.py for what a worker is."""

from __future__ import annotations

from ... import host
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

#: How every worker's system prompt opens: the Resident, speaking to its own
#: assistant. A worker is a whole session of its own, short-lived and for one
#: purpose, and this is what it could not otherwise know about its situation.
BASE = (
    "You are my assistant. I am the Resident of this Aworg, the AI that looks "
    "after this machine and the software on it for its owner. I started you "
    "to do one job for me; my message to you says what it is. You are a full "
    "session of your own, and you end when you give your final reply: that "
    "reply comes to me, along with AWORG's record of every tool call you "
    "made. You cannot reach the owner. Other assistants of mine may be "
    "working in the same workspace at the same time, on other parts of what "
    "I am doing."
)


def build_prompt(context: ToolContext, tools: list[str], skills: list[str]) -> str:
    """The worker's system prompt: who it is to me, its tools, this machine,
    then the full text of any skills I gave it. My message is not in here: it
    is the worker's first message, so it is said once."""
    parts = [BASE, "YOUR TOOLS: " + ", ".join(tools)]
    paths = getattr(context, "paths", None)
    parts.append(host.worker_summary(
        context.host or host.observe(),
        workspace=paths.workspace if paths is not None else None,
    ))
    library = getattr(context, "skills", None)
    for name in skills:
        skill = library.get_any(name) if library is not None else None
        if skill is None:
            continue
        allowed, reason = library.standing(skill)
        if not allowed and reason != library.RETIRED:
            continue
        parts.append(f"# Skill: {skill.name}\n\n{skill.body().strip()}")
    return "\n\n---\n\n".join(parts)


INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": "A short label, shown to the owner in the Workers pane.",
        },
        "task": {
            "type": "string",
            "description": (
                "Your prompt for it, written for this assistant alone: the job, "
                "its bounds, and whatever it needs to know. It sees nothing "
                "else from you."
            ),
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
            system=build_prompt(context, named, [str(s) for s in (skills or [])]),
            tools=named,
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
