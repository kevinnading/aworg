"""Where an Aworg keeps its life.

The white paper draws a hard line between three kinds of state. That line is
made physical here rather than left as a convention:

    runtime state    -> state.db      configuration, connections, conversation
    private state    -> secrets.db    credentials, and later owner-private data
    workspace state  -> workspace/    the Living Workspace the Resident evolves

Keeping them in separate files from the very first milestone means that
"publish this workspace" and "never publish that" stay easy to reason about
later, when snapshots exist and the cost of untangling them would be high.
"""

from __future__ import annotations

import os
from pathlib import Path


DEFAULT_HOME_DIRNAME = ".aworg"

#: Where the Living Workspace is, when it is not the default place.
#:
#: A file holding one absolute path, written by `aworg install --workspace`.
#: A file rather than a setting in state.db because the workspace has to be
#: known before anything opens a database -- and because an owner who points
#: an Aworg at a directory full of their work should be able to see where it
#: is pointing without a running Aworg to ask.
WORKSPACE_POINTER = "workspace.path"


def resolve_home(explicit: str | None = None) -> Path:
    """Locate this Aworg's home directory.

    Precedence: an explicit argument, then AWORG_HOME, then ~/.aworg.
    """
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get("AWORG_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / DEFAULT_HOME_DIRNAME).resolve()


class Paths:
    """The layout of a single Aworg on disk."""

    def __init__(self, home: Path):
        self.home = home
        #: Resolved once. The pointer is read from disk, and `workspace` is
        #: asked on every path a tool resolves -- a file read per filename
        #: would be a strange price to pay for a value that changes when
        #: somebody runs the installer, which is not while this is running.
        self._workspace: Path | None = None

    @property
    def state_db(self) -> Path:
        return self.home / "state.db"

    @property
    def secrets_db(self) -> Path:
        return self.home / "secrets.db"

    @property
    def workspace(self) -> Path:
        """The Living Workspace: where the Resident builds, by convention.

        A suggested home for what it makes, not a boundary around what it
        may touch. AWORG is meant to help run the machine -- installing
        services, changing configuration, managing what is already there --
        and most of that lives nowhere near here. The Resident has whatever
        the account that started AWORG has; see docs/06_ARCHITECTURE.md.

        What this directory is for is the separation the white paper draws
        between what may eventually be published and what must never leave
        the machine. Keeping the built thing in one known place is what
        makes that distinction cheap later.
        """
        if self._workspace is None:
            pointed = ""
            try:
                pointed = (self.home / WORKSPACE_POINTER).read_text(
                    encoding="utf-8"
                ).strip()
            except OSError:
                pass
            self._workspace = (
                Path(pointed).expanduser() if pointed else self.home / "workspace"
            )
        return self._workspace

    @property
    def logs(self) -> Path:
        return self.home / "logs"

    @property
    def trash(self) -> Path:
        """Where deleted things go instead of ceasing to exist.

        Deleting is the one file operation with no way back, and History
        and Reversibility -- the part of the spec that would provide one --
        are deliberately not built yet. A Resident that can permanently
        destroy an owner's work in a product with no undo anywhere is not
        a trade worth making for the sake of freeing disk.

        So delete_file moves things here, one folder per deletion, each
        holding what was deleted and a note of where it came from. That is
        enough to put it back, which is what makes this a down payment on
        Reversibility rather than a bin nobody can reach into.

        Outside the workspace on purpose. What is in the workspace is what
        the Resident is building; a trash folder among it would be
        something the Resident has to be told to ignore, and would land in
        any snapshot taken of the work.
        """
        return self.home / "trash"

    @property
    def capabilities(self) -> Path:
        """Capabilities the owner installed, beside their skills and personas.

        A capability is a folder of Tools, so installing one is copying it
        here -- the same as a skill, and for the same reason. What lands here
        is code that AWORG imports and runs, with everything AWORG itself
        has: that is the bargain, and it is the owner's to make. Nothing is
        sandboxed, nothing is asked at call time, and what protects an owner
        is knowing where a capability came from before it is in this folder.

        The built-in Capabilities are not here. They live in the package,
        because an Aworg without a filesystem or a shell is not a smaller
        Aworg, and a folder the owner can delete should not be able to take
        those away.
        """
        return self.home / "capabilities"

    @property
    def skills(self) -> Path:
        """Procedures this Aworg knows, beyond the ones it shipped with.

        The owner's, and the Resident's own: a skill is a folder with a
        SKILL.md in it, so a Resident that works out how to do something
        well can write one here with the tools it already has. Nothing
        special is needed to install a skill, which is the point of the
        format being files rather than configuration.
        """
        return self.home / "skills"

    @property
    def personas(self) -> Path:
        """Personas the owner installed, beyond the ones that shipped.

        Alongside skills/ and for the same reason: a persona is a folder of
        ordinary files, so installing one is copying it here and nothing
        else. That is what makes them exchangeable.
        """
        return self.home / "personas"

    def set_workspace(self, where: Path | None) -> "Paths":
        """Point this Aworg's workspace at a directory of the owner's choosing.

        Written down rather than remembered, because the next process has to
        find the same one. None puts it back to the default.
        """
        pointer = self.home / WORKSPACE_POINTER
        self.home.mkdir(parents=True, exist_ok=True)
        if where is None:
            pointer.unlink(missing_ok=True)
        else:
            pointer.write_text(str(Path(where).expanduser().resolve()) + "\n",
                               encoding="utf-8")
        self._workspace = None
        return self

    def ensure(self) -> "Paths":
        self.home.mkdir(parents=True, exist_ok=True)
        # parents=True: an owner may have pointed the workspace somewhere
        # that does not exist yet, and the rest are always under the home.
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.logs.mkdir(exist_ok=True)
        self.trash.mkdir(exist_ok=True)
        self.skills.mkdir(exist_ok=True)
        self.personas.mkdir(exist_ok=True)
        self.capabilities.mkdir(exist_ok=True)
        return self

    def __repr__(self) -> str:
        return f"Paths(home={self.home!s})"
