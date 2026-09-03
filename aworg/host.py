"""What AWORG can observe about the machine it lives on.

A Resident that installs things has to know what it is installing onto. Which
package manager exists, whether it can elevate, what is already present, how
much disk there is to use. Without that it guesses, and a guess about a host
is a command that fails in a way the owner has to interpret.

So the facts are gathered rather than assumed, and gathered from the machine
rather than from the Resident's expectations of it.

Everything here comes from the standard library. AWORG has four dependencies
and adding a fifth to answer "how much memory is there" would be a poor
trade; the two facts the stdlib will not give portably -- total memory, and
whether we are elevated -- are small enough to reach for directly. Measured
at about 230ms in total, which is why it is done at startup rather than once
at install: a machine surveyed at install time is wrong the first time its
owner installs anything.

Startup is not enough either. An Aworg is started once and then runs for
weeks -- that is the point of it -- so facts gathered at boot are stale by
the second day. They are re-gathered whenever they are older than a few
hours, which costs a quarter of a second somewhere between one owner's
message and the next.

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


#: Programs worth knowing about before planning any work. Presence is not the
#: same as usability -- on Windows `python` may resolve to a Store stub that
#: does nothing -- so this answers "is it on PATH", and the Resident confirms
#: anything it depends on by running it.
KNOWN_TOOLS = [
    # version control and fetching
    "git", "curl", "wget",
    # runtimes
    "python3", "python", "node", "deno", "bun", "go", "cargo", "java", "ruby", "php",
    # package managers for those runtimes
    "npm", "pnpm", "yarn", "pip", "uv", "poetry",
    # building
    "make", "cmake", "gcc", "clang", "msbuild",
    # containers and services
    "docker", "podman", "systemctl", "sc",
    # data
    "sqlite3", "psql", "mysql", "redis-cli",
    # shells
    "bash", "zsh", "fish", "pwsh", "powershell",
    # elevation
    "sudo", "doas",
    # hardware
    "nvidia-smi",
]

#: System package managers, in the order they should be preferred when a
#: machine has more than one. The first match is the one to reach for.
PACKAGE_MANAGERS = [
    ("apt-get", "apt"),
    ("dnf", "dnf"),
    ("yum", "yum"),
    ("pacman", "pacman"),
    ("zypper", "zypper"),
    ("apk", "apk"),
    ("brew", "brew"),
    ("winget", "winget"),
    ("choco", "choco"),
    ("scoop", "scoop"),
]


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


def _default_shell(tools: dict[str, str]) -> str:
    """The shell a command should be run through on this machine."""
    if sys.platform == "win32":
        return "powershell" if tools.get("powershell") or tools.get("pwsh") else "cmd"
    return os.environ.get("SHELL") or ("bash" if tools.get("bash") else "sh")


def observe() -> dict[str, Any]:
    """Everything AWORG can see about its host, right now."""
    # The package managers are scanned alongside the rest, or the search
    # below would look for them in a set they were never in -- which is
    # exactly what happened, reporting "no package manager" on a machine
    # with winget on PATH.
    wanted = KNOWN_TOOLS + [exe for exe, _ in PACKAGE_MANAGERS]
    tools = {name: path for name in wanted if (path := shutil.which(name))}
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
        "elevated": _elevated(),
        "cpus": os.cpu_count(),
        "memory_total": total_memory,
        "memory_available": available_memory,
        "disk_free": disk_free,
        "disk_total": disk_total,
        "package_manager": next(
            (label for exe, label in PACKAGE_MANAGERS if exe in tools), None
        ),
        "shell": _default_shell(tools),
        "python": platform.python_version(),
        "python_executable": sys.executable,
        "tools": sorted(tools),
        #: When this was taken, so anything holding on to it can tell how
        #: old it is -- and so the interface can say so rather than
        #: presenting a week-old reading as though it were current.
        "observed_at": time.time(),
        "observed_monotonic": time.monotonic(),
    }


def is_stale(facts: dict[str, Any] | None, max_age: float = STALE_AFTER) -> bool:
    """Whether an observation is old enough to be worth taking again.

    Measured on the monotonic clock, so that the machine's wall clock being
    corrected -- or the laptop waking from sleep -- cannot make a fresh
    reading look ancient or an ancient one look fresh.
    """
    if not facts:
        return True
    taken = facts.get("observed_monotonic")
    if taken is None:
        return True
    return (time.monotonic() - taken) > max_age


def _gb(value: int | None) -> str:
    return f"{value / 1_000_000_000:.0f} GB" if value else "unknown"


def summary(facts: dict[str, Any]) -> str:
    """The host, compactly enough to send with every message.

    About 140 tokens -- under two per cent of even a small window, and the
    difference between a Resident that proposes `apt install` on Windows and
    one that does not. Sent every turn, because a fact the Resident has to
    ask for is a fact it will forget to ask for.
    """
    elevated = facts["elevated"]
    privilege = (
        "You are running with administrator or root privileges."
        if elevated
        else "You are not elevated; anything needing root or administrator will fail "
             "unless the owner has arranged otherwise."
        if elevated is False
        else "Whether you are elevated could not be determined."
    )

    lines = [
        f"You are running on {facts['os']} {facts['release']} ({facts['arch']}), "
        f"host {facts['hostname']}, as {facts['user']}.",
        f"{facts['cpus']} CPUs, {_gb(facts['memory_total'])} memory, "
        f"{_gb(facts['disk_free'])} free disk.",
        privilege,
    ]
    if facts["package_manager"]:
        lines.append(f"System package manager: {facts['package_manager']}.")
    else:
        lines.append("No system package manager was found on PATH.")
    lines.append(f"Default shell: {facts['shell']}. Python {facts['python']}.")
    if facts["tools"]:
        lines.append(f"On PATH: {', '.join(facts['tools'])}.")
    lines.append(
        "These are observed facts about this machine. Do not assume anything "
        "not listed is installed -- check before relying on it."
    )
    return "\n".join(lines)
