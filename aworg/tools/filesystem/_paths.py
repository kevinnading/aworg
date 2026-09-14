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

    The one hard boundary in this file, and it is not about the workspace.
    An Aworg's home holds state.db, secrets.db, the trash and every
    conversation the owner has had; `delete_file("~/.aworg")` would take the
    owner's credentials, their history and the record of what happened to
    them, and the trash it would have been recoverable from goes with it.

    Nothing else here is fenced. This is not a rule about where the Resident
    may work -- it is the machine refusing to be asked to saw through the
    branch it is sitting on.
    """
    paths = getattr(context, "paths", None)
    if paths is None:
        return
    home = Path(paths.home).resolve()
    try:
        candidate = path.resolve()
    except OSError:
        return
    if candidate == home or home in candidate.parents:
        # The workspace is inside the home and is the one part of it that is
        # the Resident's to change.
        workspace = Path(paths.workspace).resolve()
        if candidate == workspace or workspace in candidate.parents:
            return
        raise ToolError(
            f"That is inside this Aworg's own home ({home}), which holds its "
            f"settings, its credentials and its conversation. Refusing to "
            f"{verb} it. The Living Workspace at {workspace} is the part that "
            "is yours to change."
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
