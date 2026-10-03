"""Read a procedure the Aworg knows.

The other half of progressive disclosure. Every offered skill's name and
description is in the system prompt; the body is here, read when it is used.
"""

from __future__ import annotations

from ..base import ToolContext, ToolError, ToolResult, size_for_model


NAME = "read_skill"

#: This tool describes itself at discovery rather than from the constants
#: below, because its enumeration is the skill library and that changes
#: without any code changing. See describe_for at the foot of this file, and
#: the argument for it, which is measured rather than aesthetic.
DYNAMIC = True

DESCRIPTION = "Load the full text of one of the skills listed in your prompt."

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

    wanted = str(skill).strip()
    found = library.get(wanted)
    if found is None:
        # Three different situations, and they used to share one sentence
        # that was wrong in two of them. The listing came from `all()`, which
        # is every skill discovered rather than every skill offered -- so
        # asking for a switched-off skill produced "There is no skill called
        # 'house-style'. You have: getting-started, house-style,
        # web-project", naming the thing in the list of what you have while
        # denying it exists. A model reading that tries again, and gets it
        # again.
        exists = getattr(library, "get_any", lambda _name: None)(wanted)
        if exists is not None:
            # Which of the three, not a guess between them. The library
            # decides this for offered() as well, so the sentence here and
            # the skill's actual standing cannot disagree.
            why = library.standing(exists)[1]
            raise ToolError(
                f"{exists.name} exists but is not available to you: {why}. "
                "Carry on without it rather than asking again. If the job "
                "genuinely needs it, say so to the owner -- the switch is "
                "theirs, not yours."
            )
        known = ", ".join(s.name for s in library.offered()) or "none"
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
        text=size_for_model(f"# Skill: {found.name}\n\n{body}", context.result_limit) + note,
        payload=body,
        summary=f"read {found.name}",
    )


def describe_for(skills: list[dict] | None = None, **_: object) -> dict:
    """This tool's descriptor, with the skill names as an enum.

    Names only. What each skill is for is in the system prompt, beside the
    name, and one copy is enough. A tool with no skills to offer returns
    nothing and is dropped.
    """
    if not skills:
        return {}
    schema = {
        "type": "object",
        "properties": {
            "skill": {
                "type": "string",
                "enum": [s["name"] for s in skills],
                "description": "Which skill to read, by name.",
            },
        },
        "required": ["skill"],
    }
    return {
        "name": NAME,
        "description": DESCRIPTION,
        "inputSchema": schema,
    }
