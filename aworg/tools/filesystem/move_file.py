"""Move or rename something.

One tool for both, because they are the same operation and a model that has
to choose between `rename_file` and `move_file` will sometimes choose wrong.
`move_file("notes.md", "notes-old.md")` renames; `move_file("notes.md",
"archive/notes.md")` moves. The distinction is in the paths, not in the verb.

Refuses to write over something that already exists. The Resident can hold
two files and be asked to combine them; it cannot be asked to make one of
them silently stop existing, because the one it destroyed would not be in the
trash and nothing would say it had gone.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from ..base import ToolContext, ToolError, ToolResult, resolve_path
from ._paths import describe, refuse_if_ours, target


NAME = "move_file"

DESCRIPTION = (
    "Move or rename a file or folder. Will not write over something that "
    "already exists."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "source": {
            "type": "string",
            "description": (
                "What to move. A relative path is taken as relative to the "
                "Living Workspace."
            ),
        },
        "destination": {
            "type": "string",
            "description": (
                "Where it should end up, including its new name. Missing "
                "parent folders are created."
            ),
        },
    },
    "required": ["source", "destination"],
}


async def run(context: ToolContext, source: str, destination: str) -> ToolResult:
    origin = target(context, source)
    refuse_if_ours(context, origin, "move")

    landing = resolve_path(context, destination)
    # A destination that is an existing folder means "put it in there", which
    # is what every file manager does and what a model means by
    # move_file("logo.svg", "assets").
    if landing.is_dir():
        landing = landing / origin.name
    refuse_if_ours(context, landing, "move onto")

    if landing.exists():
        raise ToolError(
            f"There is already something at {landing}. Nothing was moved -- "
            "delete it first if you mean to replace it."
        )
    if origin.resolve() == landing.resolve():
        raise ToolError("The source and the destination are the same place.")

    try:
        landing.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(origin), str(landing))
    except OSError as exc:
        raise ToolError(f"It could not be moved: {exc}") from None

    root = getattr(getattr(context, "paths", None), "workspace", None)
    was, now = describe(origin, root), describe(landing, root)
    renamed = origin.parent.resolve() == landing.parent.resolve()
    return ToolResult(
        text=(
            f"Renamed {was} to {landing.name}." if renamed
            else f"Moved {was} to {now}."
        ),
        summary=f"{origin.name} -> {landing.name}",
    )
