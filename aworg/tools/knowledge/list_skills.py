"""Every skill installed on this machine, including the ones switched off.

The counterpart to read_skill, and deliberately a different question.
read_skill asks "how do I do this job", and only ever sees what the owner
has left switched on. This asks "what does this machine know", and sees
everything -- because a Resident that cannot see a disabled skill cannot
tell its owner they have one.

**Seeing is not using.** Nothing here returns a body, and nothing here
switches anything on. The Resident may say "you have a skill for this and it
is off"; the owner decides. That split is the whole point: the switch stays
where it was, and the blindness goes.
"""

from __future__ import annotations

from ..base import ToolContext, ToolError, ToolResult


NAME = "list_skills"

DESCRIPTION = (
    "List every skill installed, switched on or not, with what each is for. "
    "One that is off cannot be read until the owner switches it on."
)

INPUT_SCHEMA = {"type": "object", "properties": {}}


async def run(context: ToolContext) -> ToolResult:
    library = getattr(context, "skills", None)
    if library is None:
        raise ToolError("Skills are not wired up in this Aworg.")

    installed = library.all()
    if not installed:
        return ToolResult(
            text=(
                "This Aworg has no skills installed at all. A skill is a "
                "folder with a SKILL.md in it; the owner adds them."
            ),
            summary="no skills",
        )

    ready, held = [], []
    for skill in installed:
        # Asked rather than worked out here. The library owns the three
        # reasons a skill can be held back, and offered() filters on the
        # same answer -- so this cannot drift out of step with what the
        # Resident is actually given.
        available, why = library.standing(skill)
        line = f"  {skill.name}: {skill.description}"
        (ready if available else held).append(
            line if available else f"{line}\n      Not available: {why}."
        )

    parts = []
    if ready:
        parts.append(
            f"Available to you now ({len(ready)}) -- read any of these with "
            "read_skill:\n" + "\n".join(ready)
        )
    if held:
        parts.append(
            f"Installed but not available to you ({len(held)}):\n"
            + "\n".join(held)
            + "\n\nYou cannot read these or switch them on. If one of them "
            "is what a job needs, say so to the owner in your own words and "
            "let them decide -- the switch is theirs."
        )

    return ToolResult(
        text="\n\n".join(parts),
        summary=f"{len(ready)} on, {len(held)} off",
    )
