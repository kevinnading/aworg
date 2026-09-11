"""Read a file, or a window onto part of one."""

from __future__ import annotations

from ..base import ToolContext, ToolError, ToolResult, resolve_path, size_for_model


NAME = "read_file"

DESCRIPTION = (
    "Read the contents of a text file. Returns the text with line numbers. "
    "Use offset and limit to read part of a large file rather than all of it."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": (
                "Path to the file. A relative path is taken as relative to "
                "the Living Workspace."
            ),
        },
        "offset": {
            "type": "integer",
            "description": "First line to read, 1-based. Defaults to the start.",
        },
        "limit": {
            "type": "integer",
            "description": "How many lines to read. Defaults to 500.",
        },
    },
    "required": ["path"],
}

#: A default that fits a small model's window with room left to think. Paging
#: is the interface for anything longer; the size cap in size_for_model is
#: only the net underneath it.
DEFAULT_LIMIT = 500


async def run(
    context: ToolContext,
    path: str,
    offset: int = 1,
    limit: int = DEFAULT_LIMIT,
) -> ToolResult:
    target = resolve_path(context, path)

    if not target.exists():
        raise ToolError(f"There is no file at {target}.")
    if target.is_dir():
        raise ToolError(
            f"{target} is a directory, not a file. Use search_files to see "
            "what is inside it."
        )

    try:
        # Read as UTF-8 and refuse to guess. Silently decoding a file some
        # other way would let the Resident act on text that is not what the
        # file says, which is the failure this tooling exists to avoid.
        raw = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise ToolError(
            f"{target} is not UTF-8 text. It may be a binary file, or it may "
            "have been written in another encoding."
        ) from None
    except OSError as exc:
        raise ToolError(f"{target} could not be read: {exc.strerror or exc}.") from None

    lines = raw.splitlines()
    total = len(lines)
    start = max(1, offset)
    window = lines[start - 1 : start - 1 + max(1, limit)]

    if not window and total:
        raise ToolError(
            f"{target} has {total} lines, so there is nothing at line {start}."
        )

    numbered = "\n".join(
        f"{start + i:>6}\t{line}" for i, line in enumerate(window)
    )
    shown_to = start + len(window) - 1

    # Say what was not shown. A model that can see it received lines 1-500 of
    # 4,000 will ask for the rest; one handed a silent extract will answer as
    # though it read the file.
    note = ""
    if total > len(window):
        note = (
            f"\n\n[Showing lines {start}-{shown_to} of {total}. "
            f"Call read_file again with offset to see more.]"
        )

    if not raw.strip():
        return ToolResult(
            text=f"{target} exists but is empty.",
            payload=raw,
            summary="empty file",
        )

    return ToolResult(
        text=size_for_model(numbered, context.result_limit) + note,
        payload=raw,
        summary=f"{len(window)} of {total} lines",
    )
