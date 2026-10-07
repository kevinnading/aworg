---
name: skill-writer
description: How to write an Agent Skill -- the folder layout, SKILL.md frontmatter rules and limits, how to word a description so the skill gets used, what belongs in the body and what does not. Use when asked to create, edit or review a skill, or to turn a repeated way of working into one.
---

# Skill writer

A skill is a folder. It works in any harness that reads Agent Skills.

    my-skill/
      SKILL.md          required
      references/       optional: longer docs, examples, data
      scripts/          optional: code the skill tells the agent to run
      assets/           optional: templates, images, files to copy

## SKILL.md

    ---
    name: my-skill
    description: What it does and when to use it, in one or two sentences.
    ---

    # Body: the instructions.

Rules for the frontmatter:

- `name`: lowercase letters, digits and hyphens; at most 64 characters; the
  same as the folder name.
- `description`: at most 1024 characters, no angle brackets. It is the only
  part an agent sees before deciding to open the skill, so it decides whether
  the skill is ever used.

## The description

Two halves, both required:

1. **What it gives**, concretely: "type scale, spacing and colour values",
   not "helps with design".
2. **When to use it**, as triggers the agent will recognise in a request:
   "Use when building or restyling any page, site or front end."

Name the nouns a request would contain. A skill about invoices that never
says "invoice", "bill" or "receipt" will not be found.

## The body

Write what the agent could not have produced alone:

- **Values**: hex codes, sizes, limits, names, versions, paths.
- **Tables**: symptom to cause, option to when-to-use.
- **Checks with a pass line**: "contrast at least 4.5:1", "status below 400".
- **Conventions for this place**: where files go, what things are called,
  which command runs it.

Leave out what any capable agent already does: "plan first", "check your
work", "be careful", "write clean code". Measured, that kind of advice does
not improve results and can make them worse.

Keep the body under about 500 lines. Move long material into `references/`
and say in the body when to read which file -- it is loaded only when
needed, so it costs nothing until then.

## Scripts

Put deterministic work in `scripts/` rather than describing it: a checker, a
converter, a generator. In the body, give the exact command to run it and
what its output means.

## Before calling it done

- The folder name equals `name`.
- The description passes the two-halves test above.
- Every file the body mentions exists.
- Ask: would a capable agent with no skill produce the same result? If yes,
  the skill is not carrying anything yet.
