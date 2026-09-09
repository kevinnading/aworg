"""Run a command on this machine.

The broadest thing the Resident can do, and the one an owner is most likely
to want switched off. It runs through whichever shell the machine actually
has -- decided once in host.py, so that the shell named in the facts the
Resident is told about is the same shell its commands go through.

Note what this tool deliberately does not do: inspect what the command
changed and report on it. A check performed by the thing being checked is
decoration; verification belongs to something looking with fresh eyes. That
argument is recorded in commit 75fd687 and it is why this file is short.
"""

from __future__ import annotations

import asyncio
import sys

from ... import host
from ..base import ToolContext, ToolError, ToolResult, resolve_path, size_for_model


NAME = "execute_command"

DESCRIPTION = (
    "Run a shell command, WAIT for it to finish, and return its output and "
    "exit code. Runs in the Living Workspace unless another directory is "
    "given. Not for servers or anything else meant to keep running -- use "
    "start_process for those."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "command": {
            "type": "string",
            "description": "The command line to run.",
        },
        "cwd": {
            "type": "string",
            "description": (
                "Directory to run in. A relative path is taken as relative "
                "to the Living Workspace. Defaults to the workspace."
            ),
        },
        "timeout": {
            "type": "integer",
            "description": "Seconds to allow before giving up. Defaults to 120.",
        },
    },
    "required": ["command"],
}

DEFAULT_TIMEOUT = 120
MAX_TIMEOUT = 600


async def run(
    context: ToolContext,
    command: str,
    cwd: str = ".",
    timeout: int = DEFAULT_TIMEOUT,
) -> ToolResult:
    if not command.strip():
        raise ToolError("No command was given.")

    workdir = resolve_path(context, cwd)
    if not workdir.exists():
        raise ToolError(f"There is no directory at {workdir} to run in.")

    seconds = max(1, min(int(timeout or DEFAULT_TIMEOUT), MAX_TIMEOUT))
    argv = _argv(command, context.host)

    context.progress(detail=command[:80])

    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(workdir),
            stdout=asyncio.subprocess.PIPE,
            # Merged rather than kept apart. Interleaved is how the output
            # actually happened, and a model reading a build needs the error
            # in the place it occurred rather than in a separate block.
            stderr=asyncio.subprocess.STDOUT,
        )
    except FileNotFoundError:
        raise ToolError(f"The shell {argv[0]!r} is not on this machine.") from None
    except OSError as exc:
        raise ToolError(f"The command could not be started: {exc}.") from None

    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=seconds)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise ToolError(
            f"The command was still running after {seconds} seconds and was "
            "stopped. If it is meant to run for a long time, start it in the "
            "background instead of waiting for it."
        ) from None

    output = stdout.decode("utf-8", errors="replace").strip()
    code = process.returncode

    # A command that launched something into the background and returned.
    # Exit 0 here means the launcher succeeded, which says nothing whatever
    # about the thing it launched -- and a Resident that reads it as success
    # tells the owner a server is running when nothing is listening. That
    # happened: "Done! The HTTP server is now running on port 8000", with
    # the port closed.
    detached = _looks_detached(command)

    if not output:
        body = f"(no output)\nExit code: {code}"
    else:
        body = f"{output}\n\nExit code: {code}"

    # A non-zero exit comes back flagged. The model should not have to infer
    # failure by reading the text, and a small one frequently will not.
    if detached and code == 0:
        body += (
            "\n\nNote: this command started something and returned "
            "immediately. Exit 0 means the launcher worked -- it is not "
            "evidence that what it started is running, and AWORG cannot see "
            "the process or its output. Use start_process instead, which "
            "keeps hold of it, or check for yourself before reporting "
            "success."
        )

    return ToolResult(
        text=size_for_model(body),
        payload=output,
        is_error=code != 0,
        summary=f"exit {code}" + (" (detached)" if detached else ""),
    )


#: Ways of saying "start this and do not wait". Not an exhaustive list and
#: not meant to be -- it catches the shapes a model actually reaches for when
#: it wants a server, which is what the warning is for.
DETACHING = ("start-process", "start /b", "nohup", "&disown", "disown")


def _looks_detached(command: str) -> bool:
    lowered = command.strip().lower()
    if any(marker in lowered for marker in DETACHING):
        return True
    # A trailing & on POSIX. Checked last and narrowly, because `&` appears
    # inside plenty of commands that do wait.
    return lowered.endswith("&") and not lowered.endswith("&&")


def _argv(command: str, facts: dict) -> list[str]:
    """The shell invocation for this machine.

    Which shell comes from the observed host facts rather than being decided
    here, so that the shell the Resident is told about and the shell its
    commands actually run through cannot drift apart. Falls back to observing
    only if nobody passed the facts in, which should not happen in the
    running product but keeps the tool usable on its own in a test.
    """
    if sys.platform != "win32":
        return ["/bin/sh", "-c", command]

    shell = (facts or host.observe()).get("shell")
    if shell in ("pwsh", "powershell"):
        return [shell, "-NoProfile", "-NonInteractive", "-Command", command]
    return ["cmd", "/c", command]
