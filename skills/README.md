# Skills

Procedures AWORG does not ship.

A skill is a folder with a `SKILL.md` in it: YAML frontmatter naming it and
saying when to use it, then the procedure itself. Optional `references/`
alongside holds whatever the procedure points at — a stylesheet to copy, a
script to run, a longer document to read when it is needed rather than on
every message.

Outside the package for the same reason capabilities are. A skill is
something an owner chose, and a skill that arrives inside the program is one
they cannot remove. What ships is the runtime; what an Aworg knows how to do
is theirs.

## What is here

- **barebones** — how this Aworg works, explained to the Resident: where
  tools come from and why some are missing, how skills are installed and
  switched on, how to plan a job into tasks small enough to finish, how to
  hand work to workers and get it back, and how to look at what it built.
  The one to copy in first, on any Aworg.

## Installing one

Copy the folder:

    cp -r skills/barebones ~/.aworg/skills/

Skills are re-read on every request, so it is available immediately — no
restart, unlike a capability. The owner switches it on or off in the Skills
pane; a switched-off skill is invisible to the Resident, which is worth
knowing when one of them insists it does not exist.

## Writing one

The economics decide the shape. Every installed skill's **description** is in
the system prompt on every single message; the **body** is read only when the
Resident asks for it with `read_skill`. So a dozen skills cost a paragraph
rather than a book — and a description that does not say *when* to use the
skill is a skill that will never be reached for.

Two things worth knowing, both learned the hard way:

**Process is not worth writing down.** A skill that says "plan first, check
your work, use real content" buys nothing: the Resident does that already, or
the standing instructions cover it. Measured against no skill at all, that
kind of skill made no difference and its prohibitions made the result worse.

**A point of view is worth writing down.** Concrete values the model cannot
infer — a palette in hex, a type scale in px, a section order, this machine's
conventions, a mechanical check it would not invent — change the output
completely. Two skills for the same job with different values produce two
visibly different results, which is the whole reason to have a library of
them.
