"""Make a folder that has nothing in it yet.

The one gap in this capability's handling of directories. Copy, move and
delete have always taken a folder as readily as a file; `write_file` creates
whatever parents its path needs. What none of them can do is produce an empty
one -- and empty ones are load-bearing. A project laid out before anything is
written into it, an `uploads/` a server expects to exist at boot, a `logs/`
that has to be there before the first line is logged.

Without this the Resident reaches for the shell, and `mkdir` through a shell
is the same work done unnamed: `New-Item -ItemType Directory` on one machine,
`mkdir -p` on another, both arriving in Activities as a command string an
owner has to read rather than as "created a folder".

Existing folders are not an error. `mkdir -p` has it right -- asking for a
folder that is already there is a request that has been granted, and a tool
that fails on it teaches a model to check first, which is a round trip spent
learning what it could have been told.
"""

from __future__ import annotations

from ..base import ToolContext, ToolError, ToolResult, resolve_path
from ._paths import describe


NAME = "make_directory"

DESCRIPTION = (
    "Create a folder, including any parent folders it needs. Writing a file "
    "already creates the folders above it."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": (
                "The folder to create. A relative path is taken as relative "
                "to the Living Workspace."
            ),
        },
    },
    "required": ["path"],
}


async def run(context: ToolContext, path: str) -> ToolResult:
    target = resolve_path(context, path)
    root = getattr(getattr(context, "paths", None), "workspace", None)
    where = describe(target, root)

    if target.is_dir():
        return ToolResult(
            text=f"{where} already exists, so nothing was created.",
            payload={"path": str(target), "created": False},
            summary="already there",
        )
    if target.exists():
        # A file sitting where a folder was asked for. Saying which it is
        # beats "cannot create directory": the Resident's next move is to
        # pick another name or to deal with the file, and it needs to know
        # which situation it is in.
        raise ToolError(
            f"{where} already exists and is a file, not a folder. "
            "Choose another name, or delete that file first."
        )

    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ToolError(
            f"{where} could not be created: {exc.strerror or exc}."
        ) from None

    return ToolResult(
        text=f"Created the folder {where}. It is empty.",
        payload={"path": str(target), "created": True},
        summary="folder created",
    )
