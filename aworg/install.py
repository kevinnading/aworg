"""Putting an Aworg on a machine.

Installing the package and installing an Aworg are two different acts, and
conflating them is what left the home directory half empty. `pip install
aworg` puts the program on the machine. This puts an *Aworg* on it: a home,
its two databases, its folders, and the skills, personas and capabilities
AWORG ships -- copied into that home as ordinary folders, so that from the
first moment there is exactly one place each of them lives.

That copy is the point. Shipped content used to be read out of the package
directory, which made a shipped skill a different kind of thing from one the
owner wrote: same format, same loader, different home, invisible in the
folder where an owner would look for it. Now a shipped persona is a folder in
`personas/` beside any other, editable, deletable, and loaded by the same
code. What ships is a *seed*, not a second library.

The seed is sown once. What the owner does with it afterwards is theirs:
delete a persona and it stays deleted, edit a skill and re-running install
will not overwrite your edit. `installed.json` records what was sown so those
two facts can be told apart from "this is new in this version, put it in".
`--force` is the way back to what shipped.

The built-in Capabilities -- filesystem, shell, http, and the internal ones
that are how the Resident reaches AWORG's own subsystems -- are deliberately
not seeded. They stay inside the package because an Aworg missing them is not
a plainer Aworg, it is a broken one, and a folder an owner can delete should
never be load-bearing.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .paths import Paths


#: What AWORG ships and an Aworg then owns, in the order an owner meets it.
#: Each is a directory in the package holding folders, and a directory of the
#: same name in the home that they are copied into.
SEEDS = ("skills", "personas", "capabilities")

#: What was sown, and when. Its absence is how `start` knows an Aworg has
#: never been installed; its contents are how a second install tells a folder
#: the owner deleted from one that has not shipped yet.
RECORD = "installed.json"


def shipped_root(kind: str) -> Path:
    """Where the seed for one kind of content lives inside the package."""
    return Path(__file__).parent / kind


def record_path(paths: Paths) -> Path:
    return paths.home / RECORD


def read_record(paths: Paths) -> dict[str, Any]:
    try:
        loaded = json.loads(record_path(paths).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def is_installed(paths: Paths) -> bool:
    return record_path(paths).is_file()


def seeded(paths: Paths, kind: str) -> set[str]:
    """The folder names AWORG itself put in one of the home's folders.

    What is left of "shipped" once shipped things live in the owner's home:
    not where it is read from, but who put it there. Read once by whoever
    asks; an install that happens while an Aworg is running is not something
    that Aworg has to notice mid-sentence.
    """
    return set((read_record(paths).get("seeded") or {}).get(kind) or [])


def install(
    paths: Paths,
    force: bool = False,
    workspace: str | Path | None = None,
) -> dict[str, Any]:
    """Make this home into an Aworg, and report exactly what was done.

    Safe to run again. Nothing already in the home is touched unless `force`
    says to put it back the way it shipped.
    """
    report: dict[str, Any] = {
        "home": str(paths.home),
        "existed": paths.home.is_dir(),
        "created": [],
        "databases": [],
        "seeded": {},
    }

    if workspace is not None:
        # Recorded before ensure(), so the directory that gets created is the
        # one the owner chose rather than the default we would then abandon.
        paths.set_workspace(Path(workspace).expanduser())

    for directory in _directories(paths):
        if not directory.is_dir():
            report["created"].append(str(directory))
    paths.ensure()
    report["workspace"] = str(paths.workspace)

    # Created by asking for them. Both stores write their schema on first
    # connection, so there is no separate "create the database" step to keep
    # in step with the one that actually defines it.
    from .secrets import SecretStore
    from .storage import Store

    for label, path, make in (
        ("state.db", paths.state_db, Store),
        ("secrets.db", paths.secrets_db, SecretStore),
    ):
        fresh = not path.exists()
        make(path)
        report["databases"].append({"name": label, "created": fresh})

    previous = read_record(paths)
    sown: dict[str, list[str]] = {}
    for kind in SEEDS:
        already = set((previous.get("seeded") or {}).get(kind) or [])
        result = _seed(shipped_root(kind), getattr(paths, kind), already, force)
        report["seeded"][kind] = result
        # Everything that shipped is recorded as sown whether or not it was
        # copied this time -- including what the owner has deleted, which is
        # the fact that keeps it deleted.
        sown[kind] = sorted(
            set(result["added"]) | set(result["kept"])
            | set(result["replaced"]) | set(result["removed"])
        )

    record_path(paths).write_text(
        json.dumps(
            {
                "version": __version__,
                "installed_at": datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat(),
                "first_installed_at": previous.get("first_installed_at")
                or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                "seeded": sown,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return report


def ensure_installed(paths: Paths) -> dict[str, Any] | None:
    """Install on first start, and never again.

    Starting an Aworg that was never installed should work. It should not
    quietly re-sow every time, because "I deleted that persona and it came
    back on restart" is a bug an owner cannot diagnose.
    """
    if is_installed(paths):
        return None
    return install(paths)


def _directories(paths: Paths) -> list[Path]:
    return [
        paths.home, paths.workspace, paths.logs, paths.trash,
        paths.skills, paths.personas, paths.capabilities,
    ]


def _seed(
    source: Path, destination: Path, already: set[str], force: bool
) -> dict[str, list[str]]:
    """Copy one kind of shipped content into the home.

    Four outcomes, kept apart because they are four different facts and an
    owner reading "installed 18 personas" after deleting nine would rightly
    stop believing the rest of the output.
    """
    result: dict[str, list[str]] = {
        "added": [], "kept": [], "replaced": [], "removed": [],
    }
    if not source.is_dir():
        return result

    destination.mkdir(parents=True, exist_ok=True)
    for folder in sorted(source.iterdir()):
        if not folder.is_dir() or folder.name.startswith((".", "_")):
            continue
        target = destination / folder.name
        if target.exists():
            if force:
                shutil.rmtree(target)
                _copy(folder, target)
                result["replaced"].append(folder.name)
            else:
                result["kept"].append(folder.name)
            continue
        if folder.name in already and not force:
            # Sown once and gone now: the owner removed it, and an installer
            # that puts it back is an installer arguing with them.
            result["removed"].append(folder.name)
            continue
        _copy(folder, target)
        result["added"].append(folder.name)
    return result


def _copy(folder: Path, target: Path) -> None:
    """One shipped folder, minus what only matters inside the package.

    __pycache__ is the whole of it today: a capability that has been imported
    out of the package directory has compiled bytecode beside it, stamped
    with the path it was compiled from. Copying that into the home would put
    stale, mislabelled .pyc files where the loader will look.
    """
    shutil.copytree(
        folder, target,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".*"),
    )


def describe(report: dict[str, Any]) -> str:
    """The install, in the words someone watching a terminal needs."""
    lines = [f"Aworg home     {report['home']}"]
    lines.append(f"Workspace      {report['workspace']}")
    for database in report["databases"]:
        state = "created" if database["created"] else "already there"
        lines.append(f"{database['name']:<15}{state}")

    for kind, result in report["seeded"].items():
        parts = []
        for outcome, word in (
            ("added", "installed"), ("replaced", "put back"),
            ("kept", "left alone"), ("removed", "left out, deleted here"),
        ):
            if result[outcome]:
                parts.append(f"{len(result[outcome])} {word}")
        lines.append(f"{kind:<15}{', '.join(parts) if parts else 'nothing shipped'}")
    return "\n".join(lines)
