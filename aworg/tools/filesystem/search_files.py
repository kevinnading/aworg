"""Find files by name, or find text inside them.

One tool rather than two, because the tool surface is the scarce resource
here. The models this is developed against route reliably at around five
tools and not at fifteen (docs/06_ARCHITECTURE.md), and "list a directory",
"find files by name" and "grep for text" are one question a model asks in
three moods.
"""

from __future__ import annotations

import fnmatch
import os

from ..base import ToolContext, ToolError, ToolResult, resolve_path, size_for_model


NAME = "search_files"

DESCRIPTION = (
    "List or search files and folders. Give a path to see what is in a "
    "directory -- folders are listed with a trailing slash. Add pattern to "
    "match filenames, or contains to find files holding some text."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": (
                "Directory to look in. A relative path is taken as relative "
                "to the Living Workspace. Defaults to the workspace itself."
            ),
        },
        "pattern": {
            "type": "string",
            "description": "Filename glob, such as '*.py'. Defaults to everything.",
        },
        "contains": {
            "type": "string",
            "description": (
                "Only return files containing this text, with the matching "
                "lines shown."
            ),
        },
        "recursive": {
            "type": "boolean",
            "description": "Search subdirectories too. Defaults to true.",
        },
    },
    "required": [],
}

#: Directories never worth walking into. A Resident searching a project would
#: otherwise spend its result budget on dependencies and git internals.
IGNORED = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build", ".idea",
}

MAX_HITS = 200
MAX_MATCH_LINES = 3


async def run(
    context: ToolContext,
    path: str = ".",
    pattern: str = "*",
    contains: str = "",
    recursive: bool = True,
) -> ToolResult:
    root = resolve_path(context, path)

    if not root.exists():
        raise ToolError(f"There is no directory at {root}.")
    if not root.is_dir():
        raise ToolError(f"{root} is a file, not a directory. Use read_file for it.")

    found: list[str] = []
    searched = 0
    truncated = False

    # A plain listing, rather than a hunt for particular files: then folders
    # are part of the answer.
    listing = pattern == "*" and not contains

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in sorted(dirnames) if d not in IGNORED]
        if not recursive:
            dirnames[:] = []
            # os.walk stops here, so a non-recursive listing that skipped
            # folders would report a directory of subdirectories as empty --
            # which is what it did. The folders are named before they are
            # dropped.
            for dirname in sorted(d for d in os.listdir(dirpath)
                                  if d not in IGNORED
                                  and os.path.isdir(os.path.join(dirpath, d))):
                if listing:
                    found.append(f"{dirname}/")

        elif listing:
            for dirname in dirnames:
                full = os.path.join(dirpath, dirname)
                shown = os.path.relpath(full, root)
                # Named with a trailing slash so a folder and a file of the
                # same name are not the same line, and so an empty one still
                # appears: an empty folder that lists as nothing is how a
                # Resident concludes a directory it just made does not exist.
                found.append(shown.replace(os.sep, "/") + "/")

        for filename in sorted(filenames):
            if not fnmatch.fnmatch(filename, pattern):
                continue
            full = os.path.join(dirpath, filename)
            # Forward slashes whatever the platform, so one listing does not
            # mix `site/` with `site\app.py` -- and so a path the Resident
            # reads back out of a result can be handed straight to another
            # tool without a Windows separator riding along into a URL, a
            # config file or a shell string.
            shown = os.path.relpath(full, root).replace(os.sep, "/")

            if not contains:
                found.append(shown)
            else:
                searched += 1
                hits = _matching_lines(full, contains)
                if hits:
                    found.append(shown)
                    found.extend(f"    {n:>6}\t{line}" for n, line in hits)

            if len(found) >= MAX_HITS:
                truncated = True
                break
        if truncated:
            break

    if listing:
        # One walk produces each level's folders before that level's files,
        # so a deep tree arrives interleaved. Sorted, it reads as the tree it
        # is. Only for a plain listing: where `contains` is in play the
        # matching lines sit under their file and must not be shuffled away
        # from it.
        found.sort()

    if not found:
        where = f"{root}" + (f" matching {pattern!r}" if pattern != "*" else "")
        if contains:
            return ToolResult(
                text=(
                    f"No file in {where} contains {contains!r}. "
                    f"Searched {searched} files."
                ),
                summary="no matches",
            )
        return ToolResult(text=f"Nothing found in {where}.", summary="no matches")

    body = "\n".join(found)
    note = f"\n\n[Stopped at {MAX_HITS} results. Narrow the search to see more.]" if truncated else ""

    return ToolResult(
        text=size_for_model(f"In {root}:\n{body}", context.result_limit) + note,
        payload=body,
        summary=f"{len(found)} result{'s' if len(found) != 1 else ''}",
    )


def _matching_lines(full: str, needle: str) -> list[tuple[int, str]]:
    """Lines in one file containing the text, with their numbers.

    Unreadable files are skipped rather than reported. A search that fails
    because one binary sat in the directory is a search that is no use, and
    the model asked about text.
    """
    try:
        with open(full, "r", encoding="utf-8") as handle:
            hits = []
            for number, line in enumerate(handle, 1):
                if needle in line:
                    hits.append((number, line.rstrip("\n")[:200]))
                    if len(hits) >= MAX_MATCH_LINES:
                        break
            return hits
    except (UnicodeDecodeError, OSError):
        return []
