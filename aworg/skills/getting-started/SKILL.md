---
name: getting-started
description: How to take a vague request and turn it into something you can actually build — what to ask, what not to ask, and when to stop asking and start. Use at the beginning of any new project, before planning or writing anything.
active-while: plan-is-empty
---

# Starting a project

The owner has said what they want in a sentence or two. That sentence is
never enough to build from, and interrogating them is not the answer either.

## Ask few questions, and ask them at once

Three or four, in a single message. Not one at a time — a person answering a
question every thirty seconds is being interviewed, not helped.

Ask only what changes what you would build:

- **What it is for, and who uses it.** A tool for one person on this machine
  and a thing customers will see are different projects with the same
  description.
- **The one or two things it must do.** Not a feature list; the parts that
  would make it useless if missing.
- **Anything that already exists** — data, files, a system this has to fit
  beside.

Do not ask about colours, frameworks, file layout, or anything else you are
capable of deciding. Asking the owner to make your decisions is how a project
stalls before it starts. They installed an Aworg so they would not have to
know these things.

## Do not ask at all when the request is already clear enough

"Write me a script that renames photos by date" needs no questions. Build it,
show it, and let them correct it. A first version they can look at is worth
more than a conversation about what they might want.

The test: if you can name the files you would create and be reasonably sure
they are the right ones, stop asking and start.

## Say what you understood before you build

One short paragraph: what you are going to make, the two or three main
pieces, and anything you decided for them. Not a specification — a check that
you heard the same thing they said.

If you assumed something, say which. "I am assuming this is just for you and
does not need accounts" gives them one easy thing to correct, where silence
gives them nothing until it is built.

## Name it

Once you know what the thing is, call `name_project` with a name in the
owner's words — "Chilean Soccer Game", not "soccer-game". They see it at the
top of the Application pane, and an owner who has just explained what they
want should not still be looking at "Unnamed Project".

A name is not a claim that anything works. The Lifecycle beside it answers
that, from what was observed.

## Then plan, and start

Write the tasks down with add_tasks and begin. Do not wait for approval of
the summary unless something in it is genuinely a fork in the road — the
owner can see what you are doing and can stop you.

Once there is a plan, this skill has done its job. Read a skill about the
kind of thing you are building instead.

## Through all of it

Speak as if to someone who has never written code, because they may not have.
No framework names, no file extensions, no jargon they would have to look up.
"A page listing your customers, and a way to search it" — not "a React SPA
with a filterable table component".
