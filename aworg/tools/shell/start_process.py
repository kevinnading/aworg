"""Start something that keeps running, and leave it running.

execute_command waits for a command to finish, which makes it exactly the
wrong tool for a web server, a dev server, or anything else whose whole job
is not to exit. Asked to serve a site it had just built, a Resident ran
`python -m http.server 8000` through execute_command, watched it fail, and
then spent its entire remaining round budget hunting for an interpreter --
because the failure it was shown said nothing about the real problem, which
was that the tool could never have worked.

So: start it, keep hold of it, and come back with what it printed in its
first moment. That last part matters more than it sounds. A server that dies
immediately and a server that is running both look like "started" from the
outside, and the difference is the entire question. Waiting briefly and
reporting what came out is how the Resident learns which it got, without
waiting on something designed never to finish.
"""

from __future__ import annotations

import asyncio
import sys

from ... import host
from ..base import ToolContext, ToolError, ToolResult, resolve_path, size_for_model


NAME = "start_process"

DESCRIPTION = (
    "Start a long-running program -- a web server, a dev server, a watcher --"
    " and leave it running in the background. Returns its id and whatever it "
    "printed as it started. It gets AWORG_LOG_URL and AWORG_LOG_TOKEN in its "
    "environment: POST JSON {summary, severity, where, detail} there with the"
    " token in an X-Aworg-Token header, and the failure lands in the Living "
    "Log."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "command": {
            "type": "string",
            "description": "The command line to start.",
        },
        "cwd": {
            "type": "string",
            "description": (
                "Directory to run in. Relative paths are taken as relative to "
                "the Living Workspace. Defaults to the workspace."
            ),
        },
        "name": {
            "type": "string",
            "description": "A short label, so you can recognise it later.",
        },
        "settle": {
            "type": "integer",
            "description": (
                "Seconds to watch before reporting, so a process that dies at "
                "once is caught. Defaults to 3."
            ),
        },
    },
    "required": ["command"],
}

#: How long to watch before answering. Long enough that an immediate failure
#: -- a port already taken, a missing interpreter, a syntax error -- has
#: happened and been printed; short enough that the Resident is not sitting
#: still. Almost everything that is going to fail does so in the first second.
DEFAULT_SETTLE = 3
MAX_SETTLE = 30


async def run(
    context: ToolContext,
    command: str,
    cwd: str = ".",
    name: str = "",
    settle: int = DEFAULT_SETTLE,
) -> ToolResult:
    if not command.strip():
        raise ToolError("No command was given.")

    processes = getattr(context, "processes", None)
    if processes is None:
        raise ToolError("Background processes are not wired up in this Aworg.")

    workdir = resolve_path(context, cwd)
    if not workdir.exists():
        raise ToolError(f"There is no directory at {workdir} to run in.")

    argv = _argv(command, context.host)
    watch = max(0, min(int(settle or DEFAULT_SETTLE), MAX_SETTLE))

    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(workdir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.DEVNULL,
            # The Living Log's address, handed to whatever is being started.
            #
            # This is what makes the channel real rather than documented. An
            # application does not have to be told where AWORG is or be given
            # a key -- it reads two environment variables that are simply
            # there, the way a program reads PORT. Nothing has to be wired up,
            # which matters because the thing doing the wiring would be a
            # model that forgets.
            env=context.reporting_env(),
        )
    except FileNotFoundError:
        raise ToolError(f"The shell {argv[0]!r} is not on this machine.") from None
    except OSError as exc:
        raise ToolError(f"It could not be started: {exc}.") from None

    record = processes.add(
        process, command=command, label=name or command[:40], cwd=str(workdir)
    )

    context.progress(detail=f"watching {record.id} for {watch}s")
    await asyncio.sleep(watch)

    output = processes.output(record.id)
    alive = process.returncode is None

    if not alive:
        # Died during the settle. This is the case the wait exists for, and
        # the output is the only thing that says why -- so it leads, rather
        # than being offered as an afterthought to "it exited".
        body = output.strip() or "(it printed nothing)"
        return ToolResult(
            text=(
                f"{record.label} exited immediately with code "
                f"{process.returncode}. It is not running.\n\n{size_for_model(body, context.result_limit)}"
            ),
            payload=output,
            is_error=True,
            summary=f"died at once (exit {process.returncode})",
        )

    body = output.strip()
    return ToolResult(
        text=(
            f"Started {record.label} as `{record.id}` and it is still running "
            f"after {watch}s.\n\n"
            + (f"What it printed so far:\n{size_for_model(body, context.result_limit)}\n\n" if body else "")
            + "Use list_processes to check on it or read more of its output, "
            "and stop_process to stop it. It keeps running until you do."
        ),
        payload=output,
        summary=f"running as {record.id}",
    )


def _argv(command: str, facts: dict) -> list[str]:
    """The shell invocation for this machine, matching execute_command.

    Deliberately the same rule rather than a second one. A command that works
    in execute_command and not here would be a difference the Resident has no
    way to predict.
    """
    if sys.platform != "win32":
        return ["/bin/sh", "-c", command]
    shell = (facts or host.observe()).get("shell")
    if shell in ("pwsh", "powershell"):
        return [shell, "-NoProfile", "-NonInteractive", "-Command", command]
    return ["cmd", "/c", command]
