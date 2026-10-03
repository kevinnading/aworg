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

AWORG ships no capabilities and no skills: they live in `capabilities/` and
`skills/` at the top of the repository, bound for the store, and come from
`aworg get`. Personas ship, because an Aworg with no character is a worse
first impression than one with eighteen to choose from.

The seeding below applies to all three, because a per-OS package that wants
to arrive with Chromium included copies the folders into its own `aworg/` at
build time and the installer sows them from there like anything else. In a
wheel there are no capabilities or skills to sow, and the installer says "nothing
shipped" rather than implying otherwise.
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

#: A note left in each of the three folders, for whoever opens one.
#:
#: Two of them are empty on a fresh Aworg, because AWORG ships no skills and
#: no capabilities. An empty directory says nothing about whether it is
#: broken, unused, or waiting for something, and the person most likely to
#: find it is someone poking around their own machine wondering what AWORG
#: put there. So each says what goes in it and how to put one there.
#:
#: Ignored by the loaders without needing to be: both look only at
#: directories. Written at install and then left alone, like everything else
#: here -- `--force` is what puts an edited one back.
#:
#: These are for the owner's copy. The READMEs at the top of the repository
#: are a different document for a different reader: a catalogue of what is
#: available to install. This is the note in the drawer, not the catalogue.
FOLDER_NOTES = {
    "skills": """# Skills

This folder is yours. A skill is a folder in here with a `SKILL.md`: YAML
frontmatter naming it and saying when to use it, then the procedure itself.
An optional `references/` beside it holds whatever the procedure points at.

**AWORG ships no skills**, so this folder is empty until you put something
in it. That is not a fault. What this Aworg knows how to do is yours to
choose.

To install one, `aworg get skills/NAME`, or copy its folder in here. Skills
are re-read on every request, so it is available immediately -- no restart
needed.

Switch them on and off in Settings.
""",
    "capabilities": """# Capabilities

This folder is yours. A capability is a folder in here with an `__init__.py`
declaring it and the Tools it offers.

**AWORG ships no capabilities**, so this folder is empty until you put
something in it. The built-in ones -- Filesystem, Shell, HTTP, and the
internal ones the Resident reaches AWORG's own subsystems through -- live
inside the package instead, because an Aworg missing those is not a plainer
Aworg, it is a broken one.

To install one, `aworg get tools/NAME`, or copy its folder in here. A
running Aworg notices and loads it before the next message -- no restart.

Anything installed here runs in this process, as AWORG, with the same
permissions AWORG has. There is no sandbox. That is deliberate rather than
unfinished, and it is the reason to install only what you would be willing
to run yourself.

A built-in's name cannot be taken by a folder here, and a folder here cannot
declare itself internal or required.
""",
    "personas": """# Personas

This folder is yours. A persona is a folder in here with a `PERSONA.md` and
whatever images it wears.

Unlike skills and capabilities, **these do ship** -- the installer copied
them in here as ordinary folders, so a persona AWORG wrote and one you wrote
are the same kind of thing, in the same place, loaded by the same code.

So they are yours to change. Edit one and your edit survives re-installing.
Delete one and it stays deleted. `aworg install --force` puts the shipped
ones back as they arrived, and discards your changes to them.

A persona says who the Resident is and how its chat looks, and its text is
the Resident's system prompt. Anything you want added to every persona goes
in Settings, under The Resident, rather than in here.
""",
}


#: What was sown, and when. Its absence is how `start` knows an Aworg has
#: never been installed; its contents are how a second install tells a folder
#: the owner deleted from one that has not shipped yet.
RECORD = "installed.json"


def optional(folder: Path) -> bool:
    """Whether this capability is one to leave out unless asked.

    Read from the folder rather than listed here, so that adding an optional
    capability is writing one line in its own __init__ rather than editing
    the installer. Parsed rather than imported, for the same reason the
    registry parses tool declarations: a capability that will not import is
    a capability the installer should still be able to describe.

    A capability that arrived with what it needs is not optional any more.
    That is the whole rule: complete, or absent.
    """
    declared = _declared(folder / "__init__.py")
    if not declared.get("OPTIONAL"):
        return False
    needs = declared.get("COMPLETE_WITH")
    if needs and (folder / str(needs)).is_dir():
        return False
    return True


def _declared(path: Path) -> dict[str, Any]:
    """Top-level literal assignments in a module, without importing it."""
    import ast

    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return {}
    found: dict[str, Any] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    try:
                        found[target.id] = ast.literal_eval(node.value)
                    except ValueError:
                        continue
    return found


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
    also: tuple[str, ...] | list[str] = (),
) -> dict[str, Any]:
    """Make this home into an Aworg, and report exactly what was done.

    Safe to run again. Nothing already in the home is touched unless `force`
    says to put it back the way it shipped.

    `also` names capabilities that are optional and wanted anyway -- see
    `optional`.
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
    report["notes"] = _leave_notes(paths, force)

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
        result = _seed(shipped_root(kind), getattr(paths, kind), already, force,
                       wanted=set(also) if kind == "capabilities" else None)
        if kind == "capabilities":
            # Named but not here at all. Silence would read as success, and
            # the owner would go looking for a capability that this build
            # never contained.
            here = {folder.name for folder in shipped_root(kind).iterdir()
                    if folder.is_dir()} if shipped_root(kind).is_dir() else set()
            result["unknown"] = sorted(set(also) - here)
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


def reseed(paths: Paths, kind: str) -> tuple[list[str], list[str]]:
    """Empty one of the home's content folders and sow it again.

    What a reset of that part means, now that the content is in the home:
    not "clear the switches" but "back to the ones that shipped". Everything
    goes first, including anything the owner or the Resident added, because
    a reset that carefully preserved the Resident's own skills would not be
    a reset.

    Returns what was sown and what would not delete. Failures are handed
    back rather than raised: a folder Windows will not let go of is
    something the owner has to be told about, not something that should
    abandon the rest of the reset half-done.
    """
    folder = getattr(paths, kind)
    trouble: list[str] = []
    if folder.is_dir():
        for item in folder.iterdir():
            try:
                shutil.rmtree(item) if item.is_dir() else item.unlink()
            except OSError as exc:
                trouble.append(f"{item} ({exc.strerror or exc})")
    folder.mkdir(parents=True, exist_ok=True)

    # Optional capabilities are not sown again by a reset unless they were
    # complete in the package -- "back to the way it arrived" means the way
    # it arrived here, and one the owner installed separately did not.
    result = _seed(shipped_root(kind), folder, set(), force=False,
                   wanted=set() if kind == "capabilities" else None)
    sown = sorted(set(result["added"]) | set(result["kept"]))

    # The record follows, or the next install would treat everything just
    # sown as something the owner had deleted and refuse to replace it.
    record = read_record(paths)
    seeded_now = dict(record.get("seeded") or {})
    seeded_now[kind] = sown
    record["seeded"] = seeded_now
    record.setdefault("version", __version__)
    record_path(paths).write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8"
    )
    return sown, trouble


def ensure_installed(paths: Paths) -> dict[str, Any] | None:
    """Install on first start, and never again.

    Starting an Aworg that was never installed should work. It should not
    quietly re-sow every time, because "I deleted that persona and it came
    back on restart" is a bug an owner cannot diagnose.
    """
    if is_installed(paths):
        return None
    return install(paths)


def _leave_notes(paths: Paths, force: bool) -> list[str]:
    """Put a README in each of the three folders. Returns the ones written.

    Written only where there is none, so an owner who rewrote one keeps
    their version -- the same bargain as every other thing this installs.
    `--force` is how they get ours back.

    Not recorded in `installed.json`. What is in there is the list of things
    an owner may delete and have stay deleted, and a note explaining an
    empty folder is furniture rather than content: deleting it should mean
    "I did not want the note", and the next install putting it back is the
    right answer to that rather than a bug.
    """
    written = []
    for kind, text in FOLDER_NOTES.items():
        note = getattr(paths, kind) / "README.md"
        if note.exists() and not force:
            continue
        try:
            note.write_text(text, encoding="utf-8")
        except OSError:
            # A note is a courtesy. An Aworg that refused to install
            # because it could not write one would be trading something
            # that matters for something that does not.
            continue
        written.append(kind)
    return written


def _directories(paths: Paths) -> list[Path]:
    return [
        paths.home, paths.workspace, paths.logs, paths.trash,
        paths.skills, paths.personas, paths.capabilities,
    ]


def _seed(
    source: Path, destination: Path, already: set[str], force: bool,
    wanted: set[str] | None = None,
) -> dict[str, list[str]]:
    """Copy one kind of shipped content into the home.

    Four outcomes, kept apart because they are four different facts and an
    owner reading "installed 18 personas" after deleting nine would rightly
    stop believing the rest of the output.
    """
    result: dict[str, list[str]] = {
        "added": [], "kept": [], "replaced": [], "removed": [], "optional": [],
    }
    if not source.is_dir():
        return result

    destination.mkdir(parents=True, exist_ok=True)
    for folder in sorted(source.iterdir()):
        if not folder.is_dir() or folder.name.startswith((".", "_")):
            continue
        target = destination / folder.name
        if (
            wanted is not None
            and folder.name not in wanted
            and not target.exists()
            and optional(folder)
        ):
            # Listed rather than skipped in silence: an owner who wondered
            # where the browser went is owed the answer and the way to get
            # it, and that is a line of output rather than a support thread.
            result["optional"].append(folder.name)
            continue
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
            if result.get(outcome):
                parts.append(f"{len(result[outcome])} {word}")
        lines.append(f"{kind:<15}{', '.join(parts) if parts else 'nothing shipped'}")

    unknown = report["seeded"].get("capabilities", {}).get("unknown") or []
    if unknown:
        lines.append("")
        lines.append(
            "Asked for, and not in this build of AWORG: " + ", ".join(unknown)
            + ". The prepackaged downloads carry more than the pip install "
            "does."
        )

    skipped = report["seeded"].get("capabilities", {}).get("optional") or []
    if skipped:
        lines.append("")
        lines.append(
            "Not installed, because this build did not bring everything they "
            "need: " + ", ".join(skipped) + "."
        )
        lines.append(
            "    aworg install --with " + skipped[0] + "    installs it anyway"
        )
    return "\n".join(lines)
