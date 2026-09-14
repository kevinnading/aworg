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
        return self.home / "workspace"

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

    def ensure(self) -> "Paths":
        self.home.mkdir(parents=True, exist_ok=True)
        self.workspace.mkdir(exist_ok=True)
        self.logs.mkdir(exist_ok=True)
        self.trash.mkdir(exist_ok=True)
        self.skills.mkdir(exist_ok=True)
        self.personas.mkdir(exist_ok=True)
        return self

    def __repr__(self) -> str:
        return f"Paths(home={self.home!s})"
