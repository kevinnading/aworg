"""What is still running, and what it has been saying."""

from __future__ import annotations

from ..base import ToolContext, ToolError, ToolResult, size_for_model


NAME = "list_processes"

DESCRIPTION = (
    "List the programs you started with start_process, whether each is still "
    "running, and read their recent output. Use this to check on a server "
    "you started, or to find out why one stopped."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "process": {
            "type": "string",
            "description": (
                "A process id, to read that one's output in full. Omit to "
                "list them all."
            ),
        },
        "lines": {
            "type": "integer",
            "description": "How many recent lines of output to show. Defaults to 40.",
        },
    },
    "required": [],
}

DEFAULT_LINES = 40


async def run(
    context: ToolContext, process: str = "", lines: int = DEFAULT_LINES
) -> ToolResult:
    processes = getattr(context, "processes", None)
    if processes is None:
        raise ToolError("Background processes are not wired up in this Aworg.")

    if process:
        record = processes.get(process.strip())
        if record is None:
            known = ", ".join(r.id for r in processes.all()) or "none"
            raise ToolError(
                f"There is no process {process!r}. Started this session: {known}."
            )
        body = processes.output(record.id, max(1, lines)) or "(it has printed nothing)"
        state = (
            f"running, up {record.uptime:.0f}s"
            if record.alive
            else f"stopped, exit code {record.process.returncode}"
        )
        return ToolResult(
            text=f"{record.id} {record.label} -- {state}\n\n{size_for_model(body)}",
            payload=processes.output(record.id),
            summary=state,
        )

    everything = processes.all()
    if not everything:
        return ToolResult(
            text="You have not started any background processes.", summary="none"
        )

    rows = []
    for record in everything:
        state = (
            f"running  up {record.uptime:>5.0f}s"
            if record.alive
            else f"stopped  exit {record.process.returncode}"
        )
        rows.append(f"  {record.id}  {state}  {record.label}")

    running = sum(1 for r in everything if r.alive)
    return ToolResult(
        text="\n".join(rows) + "\n\nUse list_processes with a process id to read its output.",
        summary=f"{running} running of {len(everything)}",
    )
