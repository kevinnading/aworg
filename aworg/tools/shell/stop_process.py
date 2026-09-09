"""Stop something that is still running."""

from __future__ import annotations

from ..base import ToolContext, ToolError, ToolResult


NAME = "stop_process"

DESCRIPTION = (
    "Stop a program you started with start_process. It is asked to stop "
    "first and only forced if it will not."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "process": {"type": "string", "description": "The process id to stop."},
    },
    "required": ["process"],
}


async def run(context: ToolContext, process: str = "") -> ToolResult:
    processes = getattr(context, "processes", None)
    if processes is None:
        raise ToolError("Background processes are not wired up in this Aworg.")
    if not str(process).strip():
        raise ToolError("No process id was given.")

    record = processes.get(process.strip())
    if record is None:
        known = ", ".join(r.id for r in processes.all()) or "none"
        raise ToolError(f"There is no process {process!r}. Started this session: {known}.")

    outcome = await processes.stop(record.id)
    return ToolResult(
        text=(
            f"{record.label} ({record.id}) {outcome}."
            + (
                " It did not stop when asked, so it was forced."
                if outcome == "killed" else ""
            )
        ),
        summary=outcome,
    )
