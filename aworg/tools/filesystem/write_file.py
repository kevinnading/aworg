"""Write a file, deciding the encoding rather than inheriting one.

This tool exists because of a specific failure. A Resident writing files by
echoing them through a PowerShell redirect produced UTF-16 with a BOM, which
is what that shell's `>` does by default -- and every check the Resident made
passed, because it read the file back through the same shell that wrote it.
The file was unreadable to everything else on the machine and the Resident
reported success.

A tool that writes files decides the encoding itself, and the question never
arises. That is the whole argument for this file existing: see the reasoning
recorded in commit 75fd687.
"""

from __future__ import annotations

from ..base import ToolContext, ToolError, ToolResult, resolve_path


NAME = "write_file"

DESCRIPTION = (
    "Write text to a file, creating it and any parent directories if needed. "
    "Replaces the whole file. Always writes UTF-8."
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
        "content": {
            "type": "string",
            "description": "The complete contents to write.",
        },
    },
    "required": ["path", "content"],
}


async def run(context: ToolContext, path: str, content: str) -> ToolResult:
    target = resolve_path(context, path)

    if target.is_dir():
        raise ToolError(f"{target} is a directory, so a file cannot be written there.")

    existed = target.exists()
    previous_size = target.stat().st_size if existed else 0

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # UTF-8, no BOM, and newline="" so the string is written exactly as
        # given rather than having every \n rewritten to \r\n on Windows.
        # Both are decisions rather than defaults, which is the point of
        # writing files through a tool at all.
        with open(target, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
    except OSError as exc:
        raise ToolError(f"{target} could not be written: {exc.strerror or exc}.") from None

    written = target.stat().st_size
    lines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
    verb = "Replaced" if existed else "Created"

    return ToolResult(
        text=(
            f"{verb} {target} -- {lines} lines, {written:,} bytes, UTF-8."
            + (f" It was {previous_size:,} bytes before." if existed else "")
        ),
        payload=content,
        summary=f"{'replaced' if existed else 'created'} {target.name}",
    )
