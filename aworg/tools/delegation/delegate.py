"""Hand one bounded job to one worker.

**One tool with an enumeration, not one tool per worker.** That is the whole
shape of this file and it is a decision recorded in docs/06_ARCHITECTURE.md
rather than a convenience.

Tool-selection accuracy falls away as the tool surface grows -- measured on
the models this is developed against, routing is reliable at around five tools
and not at fifteen. One tool per worker would put the Resident back in that
territory the moment an owner defined a few specialists. An enumeration keeps
the surface flat however many workers exist, and turns the Resident's job into
routing: picking a name out of a list, which even very small models do well.

The consequence is that a worker's *description* is load-bearing. It is the
only thing the Resident routes on, so a vague one is a misrouted job that the
owner experiences as the wrong specialist doing their work without ever seeing
why.
"""

from __future__ import annotations

from ..base import ToolContext, ToolError, ToolResult


NAME = "delegate"

#: This tool describes itself at call time rather than at discovery: its
#: enumeration is the owner's worker list, which changes without the code
#: changing. See describe_for at the foot of this file.
DYNAMIC = True

#: Filled in at discovery time from the worker list -- see `describe_for`,
#: which the registry calls so the model sees real names and real
#: descriptions rather than a parameter it has to guess the values of.
DESCRIPTION = (
    "Hand a bounded job to a worker instead of doing it yourself. Prefer this "
    "for work that is well described and self-contained, and for checking "
    "work you have already done."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "worker": {
            "type": "string",
            "description": "Which worker to use. Must be one of the names listed.",
        },
        "task": {
            "type": "string",
            "description": (
                "What the worker should do, in full. It cannot see this "
                "conversation and knows almost nothing about this machine, "
                "so include every detail it needs: exact paths, exact file "
                "contents, and the exact command to run. Give full paths to "
                "interpreters and programs rather than bare names -- a "
                "worker will run literally what you tell it to, so a command "
                "you know would fail here will fail there too."
            ),
        },
    },
    "required": ["worker", "task"],
}


async def run(context: ToolContext, worker: str = "", task: str = "") -> ToolResult:
    if not str(worker).strip():
        raise ToolError("No worker was named. Say which worker should do this.")
    if not str(task).strip():
        raise ToolError(
            f"No task was given for {worker}. A worker cannot see this "
            "conversation, so it needs the whole job written out."
        )

    spawn = getattr(context, "spawn", None)
    if spawn is None:
        # The tool is discoverable but the runtime did not hand it a way to
        # start anything -- which is a bug in AWORG rather than in the model's
        # request, so it says so plainly instead of blaming the caller.
        raise ToolError(
            "Delegation is not wired up in this Aworg. Nothing can be "
            "dispatched."
        )

    result = await spawn(str(worker).strip(), str(task).strip())
    if result is None:
        available = ", ".join(context.workers or []) or "none"
        raise ToolError(
            f"There is no worker called {worker!r}. Available workers: {available}."
        )

    return ToolResult(
        text=result.render(),
        payload=result.render(),
        # A worker whose own tool calls failed did not do the job, whatever
        # it says about it. Flagging the result is what makes the Resident
        # look at the evidence rather than accept the summary.
        is_error=bool(result.error) or bool(result.failed_calls),
        summary=(
            f"{result.worker}: {len(result.calls)} call"
            f"{'s' if len(result.calls) != 1 else ''}"
            + (f", {len(result.failed_calls)} failed" if result.failed_calls else "")
        ),
    )


def describe_for(workers: list[dict]) -> dict:
    """This tool's MCP descriptor, with the actual workers written into it.

    The enumeration has to carry the real names *and* their descriptions,
    because the model is choosing a specialist and the description is the
    only thing distinguishing them. A bare list of names would be a routing
    decision made with no information.
    """
    if not workers:
        return {}

    lines = "\n".join(f"- {w['name']}: {w['description']}" for w in workers)
    schema = {
        "type": "object",
        "properties": {
            **INPUT_SCHEMA["properties"],
            "worker": {
                "type": "string",
                "enum": [w["name"] for w in workers],
                "description": "Which worker to use.",
            },
        },
        "required": ["worker", "task"],
    }
    return {
        "name": NAME,
        "description": f"{DESCRIPTION}\n\nAvailable workers:\n{lines}",
        "inputSchema": schema,
    }
