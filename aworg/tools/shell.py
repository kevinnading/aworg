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
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from .base import Tool, ToolResult


#: Byte-order marks, and what is wrong with a file that starts with one.
#: UTF-16 is the serious case: the file is unreadable to anything that is not
#: expecting it, which on a developer's machine is nearly everything.
MARKS = [
    (b"\xff\xfe", "UTF-16"),
    (b"\xfe\xff", "UTF-16"),
    (b"\xef\xbb\xbf", "a UTF-8 byte-order mark"),
]

#: How many files to look at after a command. A bound rather than a
#: judgement: a command that rewrote four hundred files is a build, and
#: checking all of them would cost more than the check is worth.
MAX_CHECKED = 25


def _mangled(directory: Path, since: float) -> list[tuple[str, str]]:
    """Files the command just wrote that other programs will not read.

    This exists because of a failure the Resident cannot see. Under Windows
    PowerShell 5.1, `>` and `Out-File` write UTF-16, so a model creating a
    source file the ordinary way produces something git and every compiler
    will refuse -- and then verifies its work with `Get-Content`, which
    decodes UTF-16 without complaint and shows exactly what was expected.
    The check passes, the file is broken, and nothing in the conversation
    says otherwise. Telling the model not to do it does not work: a 9B was
    told, in the same prompt, and reached for Out-File anyway.

    So AWORG looks instead. This is the observed half of a result doing the
    job it is for -- reporting what happened rather than what was claimed.
    Only the directory the command ran in, only files it touched, and only
    their first three bytes.
    """
    findings: list[tuple[str, str]] = []
    try:
        entries = sorted(directory.iterdir())[:MAX_CHECKED]
    except OSError:
        return findings

    for entry in entries:
        try:
            if not entry.is_file() or entry.stat().st_mtime < since:
                continue
            with entry.open("rb") as handle:
                head = handle.read(3)
        except OSError:
            continue
        for mark, what in MARKS:
            if head.startswith(mark):
                findings.append((entry.name, what))
                break
    return findings


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
        """How to hand a command line to this machine's shell.

        On Windows, PowerShell 7 is preferred over the one that ships with
        the OS whenever it is installed. They are different enough to matter
        for the things a Resident does all day: Windows PowerShell 5.1 has no
        `&&`, and writes UTF-16 with a byte-order mark by default, which
        quietly produces source files that other tools will not read. Asking
        for `powershell` when `pwsh` is sitting right there costs the
        Resident a wasted step and sometimes a broken file.
        """
        if sys.platform == "win32":
            found = shutil.which("pwsh") or "powershell"
            return [found, "-NoProfile", "-NonInteractive", "-Command"]
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
        # Noted before the command starts, so that a file it writes counts as
        # touched. A whole second early, because file timestamps are coarser
        # than this clock on some filesystems and missing a real finding is
        # worse than glancing at one extra file.
        since = time.time() - 1
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

        observed: dict[str, Any] = {
            "command": command,
            "directory": str(where),
            "exit_code": code,
            "bytes": len(stdout or b""),
        }

        # Said in the output, not only recorded, because a fact the model is
        # not told is a fact it cannot act on -- and this one it can: it can
        # rewrite the file before going on to build against it.
        mangled = _mangled(where, since) if code == 0 else []
        if mangled:
            observed["mangled"] = [
                {"file": name, "encoding": what} for name, what in mangled
            ]
            listed = ", ".join(
                f"{name} ({what})" for name, what in mangled
            )
            output += (
                f"\n\n[AWORG observed: {listed} was written with an encoding "
                "most tools cannot read. Reading it back in this shell will "
                "look correct anyway. Rewrite it with Set-Content, or with "
                "[IO.File]::WriteAllText($path, $text), before anything else "
                "depends on it.]"
            )

        return ToolResult(output=output, observed=observed, failed=code != 0)

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
