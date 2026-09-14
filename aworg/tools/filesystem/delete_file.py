"""Delete something, recoverably.

**Nothing here unlinks anything.** A delete moves the thing into the Aworg's
trash, alongside a note of where it came from, and that distinction is the
entire reason this tool exists rather than the Resident reaching for
`Remove-Item` through the shell.

It could already delete files -- any Resident with Shell can. The missing
tool never prevented deletion; it only meant deletion happened unnamed, as a
shell string in the Activities feed that an owner has to parse to find out
what just happened to their work, and irreversibly, in a product whose
History and Reversibility are explicitly not built yet.

So the argument for this file is not that it grants a new power. It is that
the power was already there and was arriving in the worst available form.

The trash is not swept. Nothing empties it on a timer, because a bin that
quietly empties itself is a bin that fails exactly once, at the moment
somebody needed it. When History arrives this is what it will restore from.
"""

from __future__ import annotations

import json
import secrets
import shutil
import time
from datetime import datetime

from ..base import ToolContext, ToolError, ToolResult
from ._paths import describe, refuse_if_ours, target


NAME = "delete_file"

DESCRIPTION = (
    "Delete a file or folder. It moves to this Aworg's trash rather than "
    "being destroyed, so it can be recovered -- but the owner will not see "
    "it in the workspace any more. Say what you removed and why."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": (
                "What to delete. A relative path is taken as relative to the "
                "Living Workspace. A folder goes with everything in it."
            ),
        },
    },
    "required": ["path"],
}


async def run(context: ToolContext, path: str) -> ToolResult:
    doomed = target(context, path)
    refuse_if_ours(context, doomed, "delete")

    paths = getattr(context, "paths", None)
    if paths is None:
        raise ToolError("This Aworg has nowhere to put deleted files.")

    # A folder per deletion, named by when. The random tail is not decoration:
    # two deletions in the same second would otherwise share a folder and the
    # second would land inside the first.
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    bin_folder = paths.trash / f"{stamp}-{secrets.token_hex(3)}"

    was_dir = doomed.is_dir()
    size = 0
    if was_dir:
        size = sum(f.stat().st_size for f in doomed.rglob("*") if f.is_file())
        count = sum(1 for f in doomed.rglob("*") if f.is_file())
    else:
        size = doomed.stat().st_size
        count = 1

    try:
        bin_folder.mkdir(parents=True, exist_ok=True)
        # Written before the move, so a failure halfway leaves a note saying
        # what was being attempted rather than an unlabelled folder.
        (bin_folder / "origin.json").write_text(
            json.dumps(
                {
                    "path": str(doomed),
                    "deleted_at": time.time(),
                    "was_directory": was_dir,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        shutil.move(str(doomed), str(bin_folder / doomed.name))
    except OSError as exc:
        raise ToolError(f"It could not be deleted: {exc}") from None

    where = describe(doomed, getattr(paths, "workspace", None))
    what = f"folder {where} and the {count} file(s) in it" if was_dir else where
    return ToolResult(
        text=(
            f"Deleted {what}. It is in the trash at {bin_folder} if it turns "
            "out to have been needed."
        ),
        summary=f"deleted {doomed.name}",
        payload=f"{size:,} bytes moved to {bin_folder}",
    )
