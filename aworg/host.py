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
import subprocess
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


def _is_stub(path: str) -> bool:
    """Whether something on PATH is a placeholder that will not run.

    Windows ships "app execution aliases" in WindowsApps: zero-byte reparse
    points that exist so that typing `python` at an interactive prompt opens
    the Microsoft Store. Launched any other way they fail with "Python was
    not found", which reads like Python is missing on a machine that has
    three of them.

    This is worth detecting rather than leaving to the Resident to discover.
    Observed live: told `python` was on PATH, a 9B spent its entire round
    budget hunting for an interpreter -- `python --version`, `python3
    --version`, `where python`, searching Program Files -- and never wrote
    the answer it had been asked for. The facts said the tool was there. The
    facts were wrong, and being wrong about the machine is the one thing
    AWORG owes the owner not to be.

    Not a translation of the environment: nothing here rewrites a command or
    substitutes an interpreter. It only stops AWORG claiming something is
    available when it is not.

    Two steps, because the cheap test alone is wrong. Every one of these
    aliases is a zero-byte reparse point, including the ones that work --
    `winget` on this machine is exactly that shape and answers `v1.29.290`
    quite happily. So the file test only narrows the field, and each
    candidate is then actually run. A broken alias exits 9009, the shell's
    "command not found"; anything that gets far enough to return any other
    code has really executed and is not a stub.

    Only the candidates are run, which is typically two or three programs out
    of the twenty-odd looked for. Running all of them to find out would cost
    more than the whole rest of the observation.
    """
    if sys.platform != "win32":
        return False
    try:
        stat = os.lstat(path)
    except OSError:
        return False
    reparse = bool(getattr(stat, "st_file_attributes", 0) & _REPARSE_POINT)
    if not (reparse and stat.st_size == 0):
        return False

    try:
        result = subprocess.run(
            [path, "--version"],
            capture_output=True,
            # A program that decides to wait for input would otherwise hang
            # the observation, and with it the start of the Aworg.
            stdin=subprocess.DEVNULL,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        # It would not start at all, which is the thing being detected.
        return True
    return result.returncode == _COMMAND_NOT_FOUND


#: FILE_ATTRIBUTE_REPARSE_POINT.
_REPARSE_POINT = 0x400

#: What cmd returns when the name resolved to nothing runnable. A program
#: that does not understand `--version` returns its own error instead, which
#: still means it ran.
_COMMAND_NOT_FOUND = 9009


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


def _shell_version(shell: str) -> str | None:
    """Which version of that shell, when knowing makes a difference.

    Only asked of PowerShell, and only because the answer changes what a
    Resident should write: 5.1 and 7 differ on chaining and on what encoding
    a redirect produces. Nothing else here is worth a subprocess.
    """
    if shell not in ("powershell", "pwsh"):
        return None
    try:
        found = subprocess.run(
            [shell, "-NoProfile", "-NonInteractive", "-Command",
             "$PSVersionTable.PSVersion.ToString()"],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    version = (found.stdout or "").strip()
    return version or None


def _default_shell(tools: dict[str, str]) -> str:
    """The shell a command should be run through on this machine."""
    if sys.platform == "win32":
        # The newer one when it is there. Nothing runs commands yet,
        # but whatever eventually does has to reach for the same shell:
        # a fact block naming a different one from the one running the
        # commands would be worse than none.
        if tools.get("pwsh"):
            return "pwsh"
        return "powershell" if tools.get("powershell") else "cmd"
    return os.environ.get("SHELL") or ("bash" if tools.get("bash") else "sh")


def observe() -> dict[str, Any]:
    """Everything AWORG can see about its host, right now."""
    # The package managers are scanned alongside the rest, or the search
    # below would look for them in a set they were never in -- which is
    # exactly what happened, reporting "no package manager" on a machine
    # with winget on PATH.
    wanted = KNOWN_TOOLS + [exe for exe, _ in PACKAGE_MANAGERS]
    found = {name: path for name in wanted if (path := shutil.which(name))}
    # Present on PATH and present in a useful sense are different things, and
    # the difference is not academic: see _is_stub.
    stubs = {name: path for name, path in found.items() if _is_stub(path)}
    tools = {name: path for name, path in found.items() if name not in stubs}
    total_memory, available_memory = _memory_bytes()

    try:
        disk = shutil.disk_usage(os.path.expanduser("~"))
        disk_free, disk_total = disk.free, disk.total
    except OSError:
        disk_free = disk_total = None

    shell = _default_shell(tools)

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
        "shell": shell,
        "shell_version": _shell_version(shell),
        "python": platform.python_version(),
        "python_executable": sys.executable,
        "tools": sorted(tools),
        #: On PATH, and not usable. Kept apart from `tools` rather than
        #: dropped, because "there is no python here" and "there is
        #: something called python that will not run" lead to different
        #: next steps.
        "stubs": sorted(stubs),
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


def _shell_notes(shell: str, version: str | None) -> list[str]:
    """The handful of things about this shell that cost a wasted step.

    Not a tutorial. Every line was earned by watching a Resident get it
    wrong, and each is measured on the machine rather than recalled: the
    defaults below differ between an interactive shell and the one AWORG
    runs, which is how the first draft of this advice came out wrong.

    The encoding line is the one that matters most, and it is the least
    obvious. Under Windows PowerShell 5.1, `>` and `Out-File` write UTF-16 --
    so a Resident that creates a source file the way it has seen a thousand
    times produces something git, node, python and every compiler will refuse.
    Worse, `Set-Content -Encoding utf8` is not the fix: it adds a byte-order
    mark, where plain `Set-Content` does not.

    And the failure is invisible from inside. `Get-Content` decodes UTF-16
    happily, so a Resident that writes a file and reads it back to check its
    work sees exactly what it expected. Verifying through the tool that wrote
    something is not verification, and it is worth saying so where the
    Resident will read it before it trusts its own confirmation.
    """
    if shell not in ("powershell", "pwsh"):
        return []
    # PowerShell 7 writes UTF-8 without a BOM everywhere and has `&&`. None
    # of this applies to it, and claiming otherwise would send a Resident
    # around an obstacle that is not there.
    if not (version or "").startswith("5."):
        return []

    return [
        "PowerShell note: this is Windows PowerShell 5.1. `&&` and `||` are "
        "parse errors here -- chain with `;`, or test $? between commands "
        "when the second should only run if the first worked.",

        "PowerShell note: `>` and `Out-File` write UTF-16 here, which git, "
        "compilers and most parsers cannot read. `Set-Content -Encoding utf8` "
        "adds a byte-order mark and is not the fix. To write a text file use "
        "plain `Set-Content`, or [IO.File]::WriteAllText($path, $text) when "
        "the exact bytes matter. Note that `Get-Content` reads UTF-16 back "
        "without complaint, so reading a file you just wrote does not tell "
        "you whether anything else on this machine can read it.",

        "PowerShell note: running .ps1 files may be blocked by execution "
        "policy. Prefer passing the command directly; if you must use a "
        "script file, invoke it with -ExecutionPolicy Bypass.",
    ]


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
    shell = facts["shell"]
    version = facts.get("shell_version")
    lines.append(
        f"Commands run through {shell}"
        + (f" {version}" if version else "")
        + "."
    )
    # The interpreter AWORG itself runs on, named by its full path. The bare
    # version was misleading: it described a Python the Resident had no way
    # to invoke, while the `python` it could type resolved to something else
    # entirely. A path is a fact the Resident can act on.
    lines.append(
        f"AWORG runs on Python {facts['python']} at {facts['python_executable']}."
    )
    lines.extend(_shell_notes(shell, version))
    if facts["tools"]:
        lines.append(f"On PATH: {', '.join(facts['tools'])}.")
    if facts.get("stubs"):
        lines.append(
            f"On PATH but NOT usable: {', '.join(facts['stubs'])}. These are "
            "Windows Store placeholder aliases -- they are zero-byte stubs "
            "that fail with \"not found\" when run from a script, even though "
            "the real program may well be installed. Do not try to make them "
            "work; use a full path to a real installation instead."
        )
    lines.append(
        "These are observed facts about this machine. Do not assume anything "
        "not listed is installed -- check before relying on it."
    )
    return "\n".join(lines)
