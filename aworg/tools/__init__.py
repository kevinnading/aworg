"""What the Resident can do.

Kept deliberately small. Every tool added is tool-selection accuracy spent,
and the models this is developed against route reliably at about five tools
and not at fifteen. A capable model tolerates a wider surface; a modest one
does not, and the design targets the modest one so that both work.
"""

from __future__ import annotations

from pathlib import Path

from .base import Registry, Tool, ToolResult
from .shell import RunCommand

__all__ = ["Registry", "Tool", "ToolResult", "RunCommand", "build_registry"]


def build_registry(workspace: Path) -> Registry:
    """The tools an Aworg has out of the box."""
    return Registry([RunCommand(workspace)])
