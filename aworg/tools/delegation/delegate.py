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
    "work you have already done. A worker cannot see or speak to the owner, "
    "so never delegate asking a question, gathering requirements, or "
    "anything else that needs a person to answer -- those are yours."
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
        # Only a worker that did not finish is a failure.
        #
        # This also flagged any worker with a single failing call, and the
        # Living Log then recorded "delegate failed" for a builder that made
        # five calls, had one fail, and created the file it was asked for.
        # Three such entries sat open after a job that had gone fine.
        #
        # The evidence is not lost by this: render() still lists every call
        # and marks the failed ones, and still says plainly when a worker's
        # report does not mention a failure. What changes is the headline,
        # which was calling a job failed on the strength of a retry.
        is_error=bool(result.error),
        summary=(
            f"{result.worker}: {len(result.calls)} call"
            f"{'s' if len(result.calls) != 1 else ''}"
            + (f", {len(result.failed_calls)} retried" if result.failed_calls else "")
        ),
    )


def describe_for(workers: list[dict] | None = None, **_: object) -> dict:
    """This tool's MCP descriptor, with the actual workers written into it.

    The enumeration has to carry the real names *and* their descriptions,
    because the model is choosing a specialist and the description is the
    only thing distinguishing them. A bare list of names would be a routing
    decision made with no information.

    Unknown live state is swallowed rather than raised on. The registry hands
    every dynamic tool the same bundle, and a tool that rejects a key meant
    for a different one would remove itself from the turn -- silently, since
    the registry treats a failed descriptor as a tool to skip.
    """
    if not workers:
        return {}

    # What each worker knows, alongside what it does.
    #
    # This is how the Resident tells a worker which skill to use: not by
    # naming one at dispatch, but by choosing the worker that already has it.
    # Routing is the thing these models do reliably -- picking a name out of
    # a described list -- and consulting a procedure unprompted is the thing
    # they do not. Putting the skills in the routing decision means the
    # reliable act carries the unreliable one.
    #
    # So a worker's skills belong in its entry for the same reason its
    # description does: they are part of what distinguishes it. "builder
    # knows house-style" is what turns "write this file" into a file written
    # the way this machine writes files.
    lines = "\n".join(
        f"- {w['name']}: {w['description']}"
        + (
            f" Knows: {', '.join(w['skills'])}."
            if w.get("skills") else ""
        )
        for w in workers
    )
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
