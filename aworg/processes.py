"""Things the Resident started that are still running.

A server, a watcher, a build in progress. These outlive the tool call that
started them, which is the entire point and also the whole difficulty: a
subprocess nobody holds a reference to is a subprocess nobody can stop, read
or report on, and on Windows it survives its parent quite happily.

So they are held here, with their output drained as it arrives. Draining is
not optional housekeeping -- a pipe nobody reads fills, and a process whose
stdout is full stops running. A web server that mysteriously freezes after a
few hundred requests is what that looks like from the outside.

This is also what lets the Lifecycle stepper eventually say "Running" on
evidence: something is up and answering, observed rather than claimed.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import pathlib
import signal
import subprocess
import sys
import time
import uuid
from collections import deque
from typing import Any


#: How much of each process's output to keep, in lines. A dev server can
#: print for days; what anyone ever wants is the start -- which says whether
#: it bound its port -- and the recent end, which says what it is doing now.
KEEP_LINES = 400

#: How long to wait for a stopped process to go before insisting. Almost
#: everything handles a terminate immediately; the ones that do not are
#: usually mid-write and worth a moment.
GRACE = 3.0


#: Where the PIDs of started processes are written, under the Aworg's home.
#: A ledger rather than a lock: it exists so the *next* Aworg can clean up
#: after one that died badly.
LEDGER = "processes.json"


def _still_running(pid: int, marker: str) -> bool:
    """Whether this pid is alive and is still the thing we started.

    The marker check is the important half. PIDs are reused, and killing
    whatever now holds a number we wrote down an hour ago would be far worse
    than leaving an orphan -- so a process only counts if its command line
    still contains a distinctive piece of what was launched.
    """
    if sys.platform == "win32":
        query = (
            "Get-CimInstance Win32_Process -Filter \"ProcessId=" + str(pid) + "\" "
            "| Select-Object -ExpandProperty CommandLine"
        )
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", query],
                capture_output=True, timeout=10, stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        line = out.stdout.decode("utf-8", "replace")
        return bool(line.strip()) and marker in line

    try:
        with open(f"/proc/{pid}/cmdline", "rb") as handle:
            return marker in handle.read().decode("utf-8", "replace")
    except OSError:
        return False


def _terminate(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True, stdin=subprocess.DEVNULL,
        )
        return
    with contextlib.suppress(OSError):
        os.kill(pid, signal.SIGTERM)


def sweep_orphans(home: pathlib.Path) -> int:
    """Kill anything a previous Aworg started and never stopped.

    This exists because a shutdown handler is not enough and a job object
    cannot help. A handler only runs on a graceful exit, so a killed or
    crashed Aworg leaves its servers running; and Windows had already placed
    those children in a job of its own, so assigning them to ours was refused
    outright with access denied.

    What is left is a ledger. Each process is written down when it starts,
    and the next Aworg reads the file and clears out whatever is still alive.
    It is not instantaneous -- an orphan outlives its parent until the next
    start -- but it is the only one of the three that survives the Aworg
    being killed, which is the case that actually happened: a server held
    port 8000 for ten hours across several restarts.
    """
    ledger = home / LEDGER
    if not ledger.exists():
        return 0
    try:
        entries = json.loads(ledger.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        ledger.unlink(missing_ok=True)
        return 0

    killed = 0
    for entry in entries if isinstance(entries, list) else []:
        pid, marker = entry.get("pid"), entry.get("marker") or ""
        if not pid or not marker:
            continue
        if _still_running(int(pid), marker):
            _terminate(int(pid))
            killed += 1
    ledger.unlink(missing_ok=True)
    return killed


class Running:
    """One process the Resident started, and what it has said."""

    def __init__(self, process: Any, command: str, label: str, cwd: str):
        self.id = f"p{uuid.uuid4().hex[:6]}"
        self.process = process
        self.command = command
        self.label = label
        self.cwd = cwd
        self.started_at = time.time()
        #: Bounded on purpose. Keeping everything a long-running server ever
        #: printed is a memory leak with a friendly name.
        self.lines: deque[str] = deque(maxlen=KEEP_LINES)
        self.pump: asyncio.Task | None = None

    @property
    def alive(self) -> bool:
        return self.process.returncode is None

    @property
    def uptime(self) -> float:
        return time.time() - self.started_at

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "command": self.command,
            "cwd": self.cwd,
            "pid": self.process.pid,
            "alive": self.alive,
            "exit_code": self.process.returncode,
            "uptime": round(self.uptime, 1),
            "lines": len(self.lines),
        }


class ProcessTable:
    """Every process started this session, running or finished.

    Finished ones are kept rather than forgotten. "It is not running" is the
    answer to a question, and an owner or a Resident asking why the site is
    down is owed "it exited with code 1 and here is what it said" rather than
    silence about something that was there a minute ago.
    """

    def __init__(self, home: Any = None) -> None:
        self._processes: dict[str, Running] = {}
        #: Where to write the ledger. None means not writing one, which is
        #: what tests want and what a caller that has no home gets.
        self._home = home

    def add(self, process: Any, command: str, label: str, cwd: str) -> Running:
        record = Running(process, command, label, cwd)
        self._processes[record.id] = record
        self._write_ledger()
        # Started immediately, because the pipe begins filling immediately.
        record.pump = asyncio.create_task(self._drain(record))
        return record

    def _write_ledger(self) -> None:
        """Record what is running, for whoever starts next.

        Rewritten whole on every change rather than appended to, so a
        stopped process leaves no entry behind and the next Aworg is not
        hunting pids that were tidied up properly.
        """
        if self._home is None:
            return
        alive = [
            {
                "pid": r.process.pid,
                # Something distinctive enough to tell a reused pid from the
                # real thing. The first two words are the interpreter and
                # what it was told to run.
                "marker": " ".join(r.command.split()[:2]),
                "label": r.label,
            }
            for r in self.all()
            if r.alive
        ]
        with contextlib.suppress(OSError):
            (self._home / LEDGER).write_text(json.dumps(alive), encoding="utf-8")

    @staticmethod
    async def _drain(record: Running) -> None:
        """Read a process's output for as long as it runs.

        Not for our benefit -- for its. An OS pipe holds a few kilobytes, and
        a process whose stdout is full blocks on its next write and stops
        doing whatever it was doing. Nothing about that looks like an error:
        the server is up, the port is open, and it has simply stopped
        answering. Reading continuously is what stops that happening.
        """
        stream = record.process.stdout
        if stream is None:
            return
        try:
            while True:
                line = await stream.readline()
                if not line:
                    break
                record.lines.append(line.decode("utf-8", "replace").rstrip("\r\n"))
        except (asyncio.CancelledError, ValueError):
            raise
        except Exception:                                 # noqa: BLE001
            # A pipe that broke because the process went. Ordinary, and not
            # worth taking anything else down over.
            pass
        finally:
            # Reap it, so `alive` stops claiming a finished process is still
            # going and the exit code becomes readable.
            with contextlib.suppress(Exception):
                await record.process.wait()

    def get(self, process_id: str) -> Running | None:
        return self._processes.get(process_id)

    def all(self) -> list[Running]:
        return list(self._processes.values())

    def output(self, process_id: str, last: int = KEEP_LINES) -> str:
        record = self._processes.get(process_id)
        if record is None:
            return ""
        lines = list(record.lines)
        return "\n".join(lines[-last:])

    async def stop(self, process_id: str) -> str:
        """Ask a process to stop, and insist if it will not.

        Terminate first: a server given the chance to close its listener and
        flush its log leaves the machine tidier than one shot in the head.
        Kill only after that has visibly not worked.
        """
        record = self._processes.get(process_id)
        if record is None:
            return "unknown"
        if not record.alive:
            return "already stopped"

        # Every command goes through a shell, so what we hold is the shell
        # and the interesting process is its child. Terminating the parent
        # therefore stops the shell and orphans the server -- which is
        # exactly what happened: stop_process reported "killed" and the site
        # carried on answering on port 8000. A tool that reports success over
        # something still running is the failure this whole project is about.
        #
        # So on Windows the tree goes, not the parent. taskkill /T /F walks
        # the children; there is no portable way to do this with terminate().
        if sys.platform == "win32":
            killer = await asyncio.create_subprocess_exec(
                "taskkill", "/PID", str(record.process.pid), "/T", "/F",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await killer.wait()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(record.process.wait(), timeout=GRACE)
            self._write_ledger()
            return "stopped" if not record.alive else "would not stop"

        # Elsewhere the shell is a process group leader, so signalling the
        # group reaches the children the same way.
        record.process.terminate()
        try:
            await asyncio.wait_for(record.process.wait(), timeout=GRACE)
            return "stopped"
        except asyncio.TimeoutError:
            record.process.kill()
            await record.process.wait()
            return "killed"

    async def stop_all(self) -> None:
        """Stop everything. For shutdown and reset, so nothing is orphaned."""
        for record in self.all():
            if record.alive:
                await self.stop(record.id)

    async def clear(self) -> int:
        """Stop everything and forget it ever happened.

        For a factory reset, where "back the way it arrived" has to include
        the things the Resident started. Stopping without forgetting would
        leave dead rows claiming to be a previous life; forgetting without
        stopping leaves a server running that nothing can now reach -- which
        is what happened: a reset Aworg showed a directory listing from a
        server it no longer knew it owned, still up after ten hours.
        """
        await self.stop_all()
        count = len(self._processes)
        for record in self.all():
            if record.pump is not None:
                record.pump.cancel()
        self._processes.clear()
        return count
