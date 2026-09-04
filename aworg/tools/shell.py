"""Running commands on the machine.

The first tool, and for a while the only one, because it is the one that
makes the others unnecessary at the start: a Resident with a shell can look
at files, write them, install things, and find out what it is working with.
Four narrow tools would each be easier for a small model to route to, but
they would also be four tools instead of one, and routing accuracy is the
scarce resource. Shell first; split it up only if practice says to.

This does not confine anything, deliberately. The command runs with the
privileges of the account that started AWORG, in whichever directory the
Resident asks for. AWORG is meant to help run the machine, and a Resident
that cannot leave one folder cannot install a service or read a system log.
Confinement is the owner's to arrange when they launch it; see
docs/06_ARCHITECTURE.md.

There is no timeout. A command that takes an hour is a command that takes an
hour, and cutting it off at some number chosen here would break exactly the
long builds and installs this exists to run. What there is instead is the
ability to stop it: the turn can be stopped from the interface, and stopping
kills the process.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

from .base import Tool, ToolResult


class RunCommand(Tool):
    name = "run_command"
    description = (
        "Run a shell command on this machine and get back its output and exit "
        "code. Use this to inspect files, create and edit them, install "
        "software, start and stop services, and check whether something "
        "worked. Runs with the privileges AWORG was started with."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The command line to run, exactly as it would be typed.",
            },
            "directory": {
                "type": "string",
                "description": (
                    "Where to run it. Defaults to the Living Workspace. "
                    "An absolute path may be given to work elsewhere on the machine."
                ),
            },
        },
        "required": ["command"],
    }

    def __init__(self, workspace: Path):
        #: Where a command runs unless told otherwise. A default, not a fence:
        #: the Resident builds here by convention, and says so when it needs
        #: to be somewhere else.
        self.workspace = workspace
        self._running: set[asyncio.subprocess.Process] = set()

    def _shell(self) -> list[str]:
        """How to hand a command line to this machine's shell."""
        if sys.platform == "win32":
            return ["powershell", "-NoProfile", "-NonInteractive", "-Command"]
        return [os.environ.get("SHELL") or "/bin/sh", "-c"]

    async def run(self, command: str, directory: str | None = None) -> ToolResult:
        command = (command or "").strip()
        if not command:
            return ToolResult("No command was given.", {"error": "empty_command"}, True)

        where = Path(directory).expanduser() if directory else self.workspace
        if not where.is_dir():
            return ToolResult(
                f"There is no directory {where}.",
                {"error": "no_such_directory", "directory": str(where)},
                True,
            )

        argv = [*self._shell(), command]
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(where),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                stdin=asyncio.subprocess.DEVNULL,
            )
        except (OSError, ValueError) as exc:
            return ToolResult(
                f"Could not start the command: {exc}",
                {"error": "spawn_failed", "command": command, "directory": str(where)},
                True,
            )

        self._running.add(process)
        try:
            # stderr is folded into stdout above, because the model wants the
            # story in the order it happened. Separating them puts a warning
            # after the failure it caused.
            stdout, _ = await process.communicate()
        except asyncio.CancelledError:
            # The turn was abandoned. Do not leave the command running: it may
            # be a build, and nobody is coming back for its output.
            process.kill()
            raise
        finally:
            self._running.discard(process)

        output = stdout.decode("utf-8", "replace") if stdout else ""
        code = process.returncode
        return ToolResult(
            output=output,
            observed={
                "command": command,
                "directory": str(where),
                "exit_code": code,
                "bytes": len(stdout or b""),
            },
            failed=code != 0,
        )

    def stop_all(self) -> int:
        """Kill anything still running. Used when a turn is stopped."""
        killed = 0
        for process in list(self._running):
            if process.returncode is None:
                try:
                    process.kill()
                    killed += 1
                except (ProcessLookupError, OSError):
                    pass
        return killed
