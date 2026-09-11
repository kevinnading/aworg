"""Read a procedure the Aworg knows.

The other half of progressive disclosure. Every skill's description is in the
system prompt on every message, so the Resident knows what exists; the body
is here, read only when it is about to be used. That split is what lets an
Aworg carry dozens of skills for the cost of a paragraph.
"""

from __future__ import annotations

from ..base import ToolContext, ToolError, ToolResult, size_for_model


NAME = "read_skill"

#: This tool describes itself at discovery rather than from the constants
#: below, because its enumeration is the skill library and that changes
#: without any code changing. See describe_for at the foot of this file, and
#: the argument for it, which is measured rather than aesthetic.
DYNAMIC = True

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
            raise ToolError(
                f"{exists.name} is not available to you right now -- either "
                "the owner has switched it off, or it only applies at a "
                "point you are past. Carry on without it; do not ask again."
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
    """This tool's MCP descriptor, with the actual skills written into it.

    **The names and descriptions go in the schema, not only in the prose.**

    Every skill's description was already on every message, in a block near
    the top of the system prompt, and no local model tested would act on it:
    six configurations, and read_skill called about once in eighteen runs.
    Four explanations were tested and eliminated -- the wording, the
    placement, thinking, model size -- and the one asymmetry left was this
    file.

    `delegate` faces the identical decision: pick one name out of a list of
    specialists, each distinguished only by a sentence. It writes that list
    into its own schema as an enum, and routing to workers is the one thing
    these models do reliably. `read_skill` asked instead for a free-text
    name "as listed in your skills", which requires the model to recall prose
    from the top of a long prompt at the moment it is scanning tool schemas.
    Small models decide by reading the schemas.

    So the enumeration comes here, where the choice is actually made. This
    costs nothing extra in the general case: it is the same descriptions, and
    if it works the prompt block can carry fewer of them.

    A tool with no skills to offer returns nothing and is dropped, which is
    the right outcome -- an Aworg with an empty library should not advertise
    a way to read from it.
    """
    if not skills:
        return {}

    schema = {
        "type": "object",
        "properties": {
            "skill": {
                "type": "string",
                "enum": [s["name"] for s in skills],
                "description": "Which skill to read.",
            },
        },
        "required": ["skill"],
    }
    return {
        "name": NAME,
        "description": DESCRIPTION,
        "inputSchema": schema,
    }
