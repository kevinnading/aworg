"""What the thing being built is called.

An Aworg starts with an Unnamed Project, and that is honest rather than
lazy -- until the Resident knows what the job is, nobody has chosen a name
and inventing one would be the interface asserting something no one decided.

The Resident owns this. There is no settings form for it, deliberately: the
owner says what they want built, and the Resident is the one that understands
the job well enough to call it something. That is the same arrangement as the
plan -- the Resident writes it, and the owner reads it in a pane.

A name is not a claim about evidence, which is why this tool exists at all in
a product that is otherwise strict about the Resident not telling the
interface things. "Ashfall" is not a statement that Ashfall works. The
Lifecycle beside it still answers that question, and still answers it from
what was observed rather than from anything said here.
"""

from __future__ import annotations

from ..base import ToolContext, ToolError, ToolResult


NAME = "name_project"

DESCRIPTION = (
    "Name what you are building, and set its version. The owner sees this "
    "at the top of the Application pane. Do it once you know what the job "
    "is -- an owner should not be looking at 'Unnamed Project' after you "
    "have understood what they asked for. Raise the version when you finish "
    "something big enough that the owner would want to tell the two apart."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": (
                "What to call it, in the owner's words rather than a "
                "filename. 'Chilean Soccer Game', not 'soccer-game'. Leave "
                "it out to change only the version."
            ),
        },
        "version": {
            "type": "string",
            "description": (
                "Short, like 1.0 or 2.3. Leave it out to change only the "
                "name."
            ),
        },
    },
}


async def run(context: ToolContext, name: str = "", version: str = "") -> ToolResult:
    store = getattr(context, "store", None)
    if store is None:
        raise ToolError("This Aworg cannot record what the project is called.")

    if not (name or "").strip() and not (version or "").strip():
        # Not an error. Asking with nothing to say is a reasonable way to
        # find out what the project is currently called, and answering is
        # cheaper than making the Resident guess or go looking.
        current = store.get_project()
        return ToolResult(
            text=(
                f"The project is called {current['name']}, version "
                f"{current['version']}. Pass a name or a version to change it."
            ),
            summary=current["name"],
        )

    before = store.get_project()
    after = store.set_project(name=name or None, version=version or None)

    changed = [
        what
        for what, old, new in (
            ("name", before["name"], after["name"]),
            ("version", before["version"], after["version"]),
        )
        if old != new
    ]
    if not changed:
        return ToolResult(
            text=(
                f"It was already called {after['name']}, version "
                f"{after['version']}. Nothing changed."
            ),
            summary="unchanged",
        )

    return ToolResult(
        text=(
            f"The project is now {after['name']}, version {after['version']}. "
            "The owner sees this at the top of the Application pane."
        ),
        summary=f"{after['name']} v{after['version']}",
    )
