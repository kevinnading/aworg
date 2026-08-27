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
        """The Living Workspace.

        Created now but untouched until Milestone 2, when the Resident gains
        the ability to act rather than only converse.
        """
        return self.home / "workspace"

    @property
    def logs(self) -> Path:
        return self.home / "logs"

    def ensure(self) -> "Paths":
        self.home.mkdir(parents=True, exist_ok=True)
        self.workspace.mkdir(exist_ok=True)
        self.logs.mkdir(exist_ok=True)
        return self

    def __repr__(self) -> str:
        return f"Paths(home={self.home!s})"
