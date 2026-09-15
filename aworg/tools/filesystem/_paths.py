"""What move, copy and delete all have to agree about.

Underscored, so the registry skips it: this is shared code, not a tool.

The three of them differ only in what they do once they have worked out which
file is meant and whether touching it is sane. Working that out in one place
is what stops `delete_file` and `move_file` disagreeing about, say, whether a
trailing slash means a directory.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..base import ToolContext, ToolError, resolve_path


def target(context: ToolContext, path: str, *, must_exist: bool = True) -> Path:
    """The file or folder a path argument means.

    Absolute paths are honoured, the same as everywhere else -- the workspace
    is a suggestion rather than a fence, and a Resident asked to tidy up
    somewhere else has been asked on purpose. See docs/06_ARCHITECTURE.md.
    """
    resolved = resolve_path(context, path)
    if must_exist and not resolved.exists():
        raise ToolError(f"There is nothing at {resolved}.")
    return resolved


def refuse_if_ours(context: ToolContext, path: Path, verb: str) -> None:
    """Stop the Resident destroying the Aworg it lives in.

    Two refusals, and they are different in kind.

    **The home itself.** state.db, secrets.db, the trash, the backups and
    every conversation the owner has had. `delete_file("~/.aworg")` would
    take their credentials, their history and the record of what happened to
    them -- and the trash it would have been recoverable from goes with it.

    **The Living Workspace, as a whole.** Everything *in* it is the
    Resident's to move, copy and delete; the directory itself is not. The
    difference is that emptying the workspace is not a file operation, it is
    a decision about the Aworg, and there is already a door for it: Settings
    has a Reset that counts what will go first, makes the owner type a code,
    copies both databases to backups/, stops whatever the Resident had
    running, and writes the Living Log entry afterwards so the silence above
    it is explained. None of that happens when a tool moves the folder into
    the trash.

    So this is not a fence around where the Resident may work -- absolute
    paths anywhere else are honoured. It is the machine declining to be asked
    to saw through the branch it is sitting on, and pointing at the stairs.
    """
    paths = getattr(context, "paths", None)
    if paths is None:
        return
    home = Path(paths.home).resolve()
    try:
        candidate = path.resolve()
    except OSError:
        return
    if not (candidate == home or home in candidate.parents):
        return

    workspace = Path(paths.workspace).resolve()
    # Inside the workspace: the Resident's own territory, allowed.
    if workspace in candidate.parents:
        return

    if candidate == workspace:
        # Phrased around the infinitive rather than conjugating `verb`:
        # callers pass "delete", "move" and "copy onto", and the last of
        # those has no past tense that a suffix will find.
        raise ToolError(
            f"Refusing to {verb} the Living Workspace itself ({workspace}). "
            "Everything inside it can be. If the owner wants it emptied, that "
            "is Reset in Settings -- it counts what will go, asks them to "
            "confirm with a code, backs up both databases and stops anything "
            "still running. Point them at it rather than doing it here."
        )

    raise ToolError(
        f"That is inside this Aworg's own home ({home}), which holds its "
        f"settings, its credentials and its conversation. Refusing to {verb} "
        f"it. The Living Workspace at {workspace} is the part that is yours "
        "to change."
    )


def describe(path: Path, root: Any = None) -> str:
    """A path as the owner would recognise it.

    Relative to the workspace where it is inside it, because `site/index.html`
    is what they call it, and absolute otherwise, because outside the
    workspace the full path is the only unambiguous name.
    """
    if root is None:
        return str(path)
    try:
        return path.resolve().relative_to(Path(root).resolve()).as_posix()
    except (ValueError, OSError):
        return str(path)
