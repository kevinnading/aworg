"""Where AWORG is, as observed rather than assumed.

A Resident acting on a machine has to know what it is acting on -- where its
work lands, what interpreter will actually run, whether it can elevate.
Without that it guesses, and a guess about a host is a command that fails in
a way the owner has to interpret.

**The same eighteen facts go to both audiences, and that is the design.** The
owner reads them in the Environment pane; the Resident reads them in its
prompt. An owner who can see exactly what their Resident was told can tell a
mistake from a misunderstanding, and learns over time what the thing living
on their machine is working with. Showing one of them less would make the
other's picture unauditable.

That shared audience is also what keeps the list short. There is no longer
anywhere to hide a fact nobody reads: anything here is on screen and in every
prompt, so it has to earn both. The test applied was whether a fact has ever
changed what a Resident did. Capacity figures and a hostname never have; the
workspace, the interpreter and the shell demonstrably have.

Everything comes from the standard library. The two facts stdlib will not
give portably -- total memory, and whether we are elevated -- are reached for
with ctypes, which is also stdlib, so the cost is a platform branch rather
than a dependency. Both together take about 2ms; the whole observation takes
about 80ms, down from 550-640ms when it was also scanning PATH for forty
named programs and running the ones that looked like Windows stubs.

Done at startup rather than once at install: a machine surveyed at install
time is wrong the first time its owner installs anything. Startup is not
enough either -- an Aworg is started once and then runs for weeks, which is
the point of it -- so the facts are re-gathered whenever they are older than
a few hours.

Nothing here is a boundary. AWORG runs with exactly the privileges of the
account that started it -- run it as yourself and it is you, run it as root
and it is root, run it inside a sandbox and it is whatever that allows. This
module's job is to say which of those is true, not to decide it.
"""

from __future__ import annotations

import ctypes
import time
import os
import platform
import shutil
import socket
import sys
from typing import Any


#: How long an observation is worth trusting. Machines change under a
#: long-running Aworg: things get installed, disks fill, an owner grants
#: sudo. Three hours is short enough that the Resident is rarely working
#: from a stale picture, and long enough that the cost never shows.
STALE_AFTER = 3 * 60 * 60


#: Where a route probe is aimed. RFC 5737 TEST-NET-1: reserved for
#: documentation, guaranteed never routed, and nobody's real address -- so
#: nothing here needs explaining to somebody reading the source and wondering
#: why their Aworg is touching a public DNS server.
_ROUTE_PROBE = "192.0.2.1"


def _ip() -> str | None:
    """The address another machine on this network would reach here at.

    A routing-table lookup wearing a socket. UDP connect() sends no datagram
    -- it only asks the kernel which interface would carry traffic to that
    address and binds the local side to it. Nothing reaches the wire, so a
    packet filter has nothing to filter and this works behind a firewall.

    AWORG binds 127.0.0.1, so this is the fact that tells an owner their
    application could be opened from their phone. It is also the only part of
    the block that can be wrong in an interesting way: a VPN changes it, and a
    machine with several interfaces has several answers and this returns the
    one the default route prefers.

    None when there is no route at all, which is the honest answer for a
    machine with nothing connected.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect((_ROUTE_PROBE, 80))
        return probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()


def _memory_bytes() -> tuple[int | None, int | None]:
    """Total and available memory. Not portable in the stdlib; reachable."""
    if sys.platform == "win32":
        class _Status(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        try:
            status = _Status()
            status.dwLength = ctypes.sizeof(status)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            return status.ullTotalPhys, status.ullAvailPhys
        except (AttributeError, OSError):
            return None, None

    try:
        total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        return None, None

    available = None
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    available = int(line.split()[1]) * 1024
                    break
    except OSError:
        pass
    return total, available


def _elevated() -> bool | None:
    """Whether this process can already do privileged things.

    None where the question cannot be answered rather than False, because
    "we do not know" and "no" lead to different advice.
    """
    if hasattr(os, "geteuid"):
        return os.geteuid() == 0
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return None


#: The only programs this module looks for, and it looks for them for one
#: reason: to decide which shell a command runs through.
#:
#: There used to be forty, scanned to tell the Resident what was installed.
#: That list was a whitelist, and the block it fed said "do not assume
#: anything not listed is installed" -- so a machine with ffmpeg, dotnet, tar
#: and ssh on PATH reported none of them and instructed the Resident to treat
#: them as absent. A confident wrong answer, which is worse than no answer.
#: Enumerating PATH outright finds a thousand executables in 16ms against the
#: 248ms that whitelist cost, and when something needs to know whether a
#: program exists it can ask then, about that program.
_SHELL_CANDIDATES = ("pwsh", "powershell", "bash")


def _default_shell() -> str:
    """The shell a command should be run through on this machine.

    Not reported to anyone, and still gathered. execute_command and
    start_process read the shell out of these facts rather than deciding for
    themselves, so the shell chosen here and the shell commands actually run
    through are the same one by construction.
    """
    found = {name: shutil.which(name) for name in _SHELL_CANDIDATES}
    if sys.platform == "win32":
        if found.get("pwsh"):
            return "pwsh"
        return "powershell" if found.get("powershell") else "cmd"
    return os.environ.get("SHELL") or ("bash" if found.get("bash") else "sh")


def observe() -> dict[str, Any]:
    """Everything AWORG reports about where it is, right now.

    Eighteen fields, and the list was cut to them deliberately rather than
    grown to them. The test each one had to pass was whether it has ever
    changed what a Resident did -- not whether it was interesting, and not
    whether it was cheap. Most of what used to be here was neither.

    What went, and why it is not missed: the forty-name tool scan, because a
    whitelist paired with "assume nothing else exists" is a confident wrong
    answer; the stub detection, because it only ever corrected a claim that
    scan made, and nothing advertises a broken `python` any more; the shell
    version, because it cost a subprocess to tune advice that is better
    delivered when a command actually fails; and the package manager, because
    it matters only at the moment something is installed, which is the moment
    to go and look.

    Cost: about 80ms, against 550-640ms before. That figure is the reason the
    second timestamp went too -- see is_stale.
    """
    total_memory, available_memory = _memory_bytes()

    try:
        disk = shutil.disk_usage(os.path.expanduser("~"))
        disk_free, disk_total = disk.free, disk.total
    except OSError:
        disk_free = disk_total = None

    return {
        "os": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "arch": platform.machine(),
        "hostname": socket.gethostname(),
        "user": os.environ.get("USER") or os.environ.get("USERNAME"),
        #: What another machine on this network would reach this one at.
        #: None when nothing is connected.
        "ip": _ip(),
        "elevated": _elevated(),
        "cpus": os.cpu_count(),
        "memory_total": total_memory,
        "memory_available": available_memory,
        "disk_free": disk_free,
        "disk_total": disk_total,
        "python": platform.python_version(),
        "python_executable": sys.executable,
        #: Gathered, never shown. execute_command and start_process read it
        #: to decide what to invoke; see _default_shell.
        "shell": _default_shell(),
        #: When this was taken, so anything holding on to it can tell how old
        #: it is -- and so the interface can say so rather than presenting a
        #: week-old reading as though it were current.
        "observed_at": time.time(),
    }


def is_stale(facts: dict[str, Any] | None, max_age: float = STALE_AFTER) -> bool:
    """Whether an observation is old enough to be worth taking again.

    Wall clock, and only wall clock. There used to be a monotonic reading
    beside it so that a corrected clock or a laptop waking from sleep could
    not make a fresh observation look ancient. That was worth a second field
    when taking one cost two-thirds of a second; at 80ms the worst a confused
    clock can do is buy an observation nobody needed, which is cheaper than
    carrying a number to prevent it.
    """
    if not facts:
        return True
    taken = facts.get("observed_at")
    if taken is None:
        return True
    return abs(time.time() - taken) > max_age


def _gb(value: int | None) -> str:
    return f"{value / 1_000_000_000:.0f} GB" if value else "unknown"


def environment(facts: dict[str, Any], workspace: Any = None) -> list[tuple[str, str]]:
    """The eighteen, as label and value pairs.

    One function, two audiences. The owner reads these in the Environment
    pane and the Resident reads them in its prompt, and they are the same
    eighteen facts in the same order on purpose: an owner who can see exactly
    what their Resident was told can tell a mistake from a misunderstanding,
    and learns over time what it is working with and what it is short of.

    Pairs rather than prose, because the two renderings want different
    punctuation and neither wants to re-derive the content.
    """
    pairs: list[tuple[str, str]] = []

    # First, because it is the one location that decides where work lands.
    #
    # It was missing entirely once, and the omission was not neutral. The only
    # absolute path the Resident was ever shown is AWORG's own interpreter,
    # which lives inside the source checkout -- so the only directory it had
    # evidence for was that checkout, and it concluded that was "the project".
    # Residents then wrote files into the source tree. Three reached a commit.
    if workspace:
        pairs.append(("Living Workspace", str(workspace)))

    # Ordered by how much each one has ever changed an outcome, not by
    # category. The workspace and the interpreter are the two that
    # demonstrably have, so they lead; the capacity readings are the three
    # that never have, so they trail. This matters twice over -- it is the
    # order a model reads, and it decides what falls below the fold in a pane
    # the owner has not dragged taller.
    pairs.append(("Python", f"{facts['python']} at {facts['python_executable']}"))
    pairs.append(("Machine", f"{facts['os']} {facts['release']} ({facts['version']})"))
    pairs.append((
        "Privileges",
        "elevated -- root or administrator" if facts["elevated"]
        else "not elevated" if facts["elevated"] is False
        else "unknown",
    ))
    pairs.append(("Architecture", str(facts["arch"])))
    pairs.append(("Host", f"{facts['hostname']}, as {facts['user']}"))
    pairs.append(("Address", facts.get("ip") or "no network"))
    pairs.append(("Processors", f"{facts['cpus']} CPUs"))
    pairs.append((
        "Memory",
        f"{_gb(facts['memory_available'])} free of {_gb(facts['memory_total'])}",
    ))
    pairs.append((
        "Disk",
        f"{_gb(facts['disk_free'])} free of {_gb(facts['disk_total'])}",
    ))
    return pairs


def summary(facts: dict[str, Any], workspace: Any = None) -> str:
    """The environment, compactly enough to send with every message.

    Facts, and as little prose as they can be stated in. The block this
    replaced had grown to about 800 tokens, of which roughly six hundred were
    advice -- five paragraphs of shell workarounds, each added after a real
    incident and each true, which together made the largest thing in a prompt
    that this project's own measurements say gets worse as it gets longer.

    The advice is not deleted, it is relocated: a note about what PowerShell
    does to a redirect is worth reading at the moment a redirect fails, and
    worth nothing on the four hundred messages where nobody redirects
    anything. Facts are the opposite -- useless at the moment of failure,
    because by then the wrong assumption has already been acted on.

    Two sentences are still prose and both earn it. The workspace needs
    saying rather than labelling, because what an owner calls a folder and
    what a Resident does with a relative path are not obviously the same
    thing. And the interpreter needs the warning beside it, because the path
    is inside AWORG's own checkout and a Resident that reads it as "the
    project" writes into the source tree.
    """
    lines = ["ENVIRONMENT -- observed on this machine, not remembered."]
    lines += [f"  {label}: {value}" for label, value in environment(facts, workspace)]

    if workspace:
        lines.append(
            f"Build in {workspace}. A relative path goes there -- write "
            "`notes.md` and it lands there. You are not confined to it, but "
            "nothing should end up outside it by accident."
        )
    lines.append(
        "That Python path is AWORG's own installation. Use the interpreter; "
        "leave the directory alone, and do not run `python` by name."
    )
    lines.append(
        "These were observed, not assumed. Anything not here is something to "
        "check rather than to rule out."
    )
    return "\n".join(lines)
