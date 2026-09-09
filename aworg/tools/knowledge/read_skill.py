"""Read a procedure the Aworg knows.

The other half of progressive disclosure. Every skill's description is in the
system prompt on every message, so the Resident knows what exists; the body
is here, read only when it is about to be used. That split is what lets an
Aworg carry dozens of skills for the cost of a paragraph.
"""

from __future__ import annotations

from ..base import ToolContext, ToolError, ToolResult, size_for_model


NAME = "read_skill"

DESCRIPTION = (
    "Read one of your skills in full. A skill tells you how to go about a "
    "kind of job. Read the relevant one before starting that kind of work, "
    "not after."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "skill": {
            "type": "string",
            "description": "The name of the skill, as listed in your skills.",
        },
    },
    "required": ["skill"],
}


async def run(context: ToolContext, skill: str = "") -> ToolResult:
    library = getattr(context, "skills", None)
    if library is None:
        raise ToolError("Skills are not wired up in this Aworg.")
    if not str(skill).strip():
        raise ToolError("No skill was named.")

    found = library.get(str(skill).strip())
    if found is None:
        known = ", ".join(s.name for s in library.all()) or "none"
        raise ToolError(f"There is no skill called {skill!r}. You have: {known}.")

    body = found.body()
    references = found.references()
    note = ""
    if references:
        # Named rather than inlined. A skill stays short enough to read by
        # pointing at its depth instead of carrying it.
        listing = "\n".join(f"  {r}" for r in references)
        note = (
            f"\n\nThis skill has further detail alongside it, which you can "
            f"read with read_file relative to {found.directory}:\n{listing}"
        )

    return ToolResult(
        text=size_for_model(f"# Skill: {found.name}\n\n{body}", limit=20000) + note,
        payload=body,
        summary=f"read {found.name}",
    )
