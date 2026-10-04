"""Change part of a file, without rewriting the whole thing.

write_file replaces everything, which is right for creating a file and badly
wrong for changing one. A one-line fix in a 500-line module means the model
reproducing all 500 lines from memory -- expensive on a small context, and
every reproduced line is a line it can quietly get wrong. The file comes back
subtly different in places nobody asked about, and nothing catches it.

So this edits by replacement: say what is there now and what should be there
instead. The old text must match exactly and must be unique, which is what
makes the edit verifiable rather than hopeful -- if it matched twice, the tool
does not guess which one was meant.
"""

from __future__ import annotations

from ..base import ToolContext, ToolError, ToolResult, resolve_path


NAME = "edit_file"

DESCRIPTION = (
    "Replace an exact piece of text in a file, leaving the rest untouched. "
    "The old text must appear exactly once."
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
        "old": {
            "type": "string",
            "description": (
                "The exact text to replace, copied from the file including "
                "its indentation. Include enough surrounding lines to make "
                "it unique."
            ),
        },
        "new": {
            "type": "string",
            "description": "What to put there instead. Empty string deletes it.",
        },
        "all": {
            "type": "boolean",
            "description": (
                "Replace every occurrence rather than requiring exactly one. "
                "Defaults to false."
            ),
        },
    },
    "required": ["path", "old", "new"],
}

#: How much of a near-miss to quote back when the text is not found. Enough
#: to see the whitespace that is usually the problem, short enough not to
#: spend the model's context on a failure.
CONTEXT_CHARS = 200


async def run(
    context: ToolContext,
    path: str,
    old: str,
    new: str = "",
    all: bool = False,
) -> ToolResult:
    target = resolve_path(context, path)

    if not target.exists():
        raise ToolError(
            f"There is no file at {target}. Use write_file to create it."
        )
    if target.is_dir():
        raise ToolError(f"{target} is a directory.")
    if not old:
        raise ToolError(
            "No text to replace was given. To create or overwrite a file, "
            "use write_file."
        )

    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise ToolError(f"{target} is not UTF-8 text.") from None
    except OSError as exc:
        raise ToolError(f"{target} could not be read: {exc.strerror or exc}.") from None

    count = content.count(old)

    if count == 0:
        # Say why rather than only that. Indentation and line endings are the
        # usual culprits, and a model told "not found" will try the same
        # thing again with a different guess.
        hint = _nearest(content, old)
        raise ToolError(
            f"That text does not appear in {target.name}. Check indentation "
            "and line breaks -- it must match exactly."
            + (f"\n\nThe closest thing in the file is:\n{hint}" if hint else "")
        )

    if count > 1 and not all:
        raise ToolError(
            f"That text appears {count} times in {target.name}, so it is not "
            "clear which was meant. Include more surrounding lines to make it "
            "unique, or pass all=true to replace every occurrence."
        )

    updated = content.replace(old, new)

    try:
        # Same decisions as write_file: UTF-8, no BOM, and the content
        # written exactly as given. An edit that changed a file's encoding
        # as a side effect would be worse than the rewrite it replaced.
        with open(target, "w", encoding="utf-8", newline="") as handle:
            handle.write(updated)
    except OSError as exc:
        raise ToolError(f"{target} could not be written: {exc.strerror or exc}.") from None

    delta = updated.count("\n") - content.count("\n")
    change = f"{delta:+d} lines" if delta else "same line count"
    return ToolResult(
        text=(
            f"Replaced {count} occurrence{'s' if count != 1 else ''} in "
            f"{target} ({change}, now {len(updated):,} bytes)."
        ),
        payload=updated,
        summary=f"edited {target.name}",
    )


def _nearest(content: str, old: str) -> str:
    """The part of the file that looks most like what was asked for.

    Matched on the first line with its whitespace stripped, which catches the
    overwhelmingly common case: the text is right and the indentation is not.
    """
    first = old.strip().splitlines()[0].strip() if old.strip() else ""
    if len(first) < 4:
        return ""
    for line in content.splitlines():
        if first in line:
            index = content.index(line)
            return content[index : index + CONTEXT_CHARS]
    return ""
