"""Copy something, leaving the original alone.

The quiet one of the three. Copying destroys nothing, so it needs no trash
and no confirmation -- the worst it can do is use disk.

It still refuses to write over an existing file, for the same reason move
does: the thing it overwrote would be gone with no record and no way back,
which is a deletion wearing a copy's name. If the Resident means to replace
something it can delete it first, and then the replaced version is in the
trash where it belongs.
"""

from __future__ import annotations

import shutil

from ..base import ToolContext, ToolError, ToolResult, resolve_path
from ._paths import describe, refuse_if_ours, target


NAME = "copy_file"

DESCRIPTION = (
    "Copy a file or folder, leaving the original where it is. Will not write "
    "over something that already exists. A folder is copied with everything "
    "in it."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "source": {
            "type": "string",
            "description": (
                "What to copy. A relative path is taken as relative to the "
                "Living Workspace."
            ),
        },
        "destination": {
            "type": "string",
            "description": (
                "Where the copy goes, including its name. An existing folder "
                "means 'put it in there'."
            ),
        },
    },
    "required": ["source", "destination"],
}


async def run(context: ToolContext, source: str, destination: str) -> ToolResult:
    origin = target(context, source)
    landing = resolve_path(context, destination)
    if landing.is_dir():
        landing = landing / origin.name
    refuse_if_ours(context, landing, "copy onto")

    if landing.exists():
        raise ToolError(
            f"There is already something at {landing}. Nothing was copied -- "
            "delete it first if you mean to replace it."
        )

    try:
        landing.parent.mkdir(parents=True, exist_ok=True)
        if origin.is_dir():
            shutil.copytree(str(origin), str(landing))
            count = sum(1 for f in landing.rglob("*") if f.is_file())
        else:
            shutil.copy2(str(origin), str(landing))
            count = 1
    except OSError as exc:
        raise ToolError(f"It could not be copied: {exc}") from None

    root = getattr(getattr(context, "paths", None), "workspace", None)
    return ToolResult(
        text=(
            f"Copied {describe(origin, root)} to {describe(landing, root)}"
            + (f", {count} files." if origin.is_dir() else ".")
        ),
        summary=f"copied {origin.name}",
    )
