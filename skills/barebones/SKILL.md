---
name: barebones
description: How this Aworg actually works — where your tools come from and why some are missing, how skills are installed and switched on, how to plan a job into tasks small enough to finish, how to hand work to workers and get it back, and how to look at what you have built. Read this when you are unsure what you can do here, when the owner refers to something in the interface you cannot see, or at the start of any job larger than one message.
---

# How this Aworg works

You live in an application the owner has open in a browser. They can see a
great deal about you: every tool call you make, the plan you are keeping, the
files in the workspace, what is running, and a log of what mattered. You
cannot see their screen. Most confusion between you and them comes from
forgetting that the two of you are looking at different things.

## Your tools come from Capabilities, and not all of them are on

A **Tool** is one thing you can call. A **Capability** is a folder of related
tools that is switched on or off as a unit. The owner sees them all in the
Capabilities pane, with a switch and a token cost beside each.

Four states, and the difference matters when you are talking to the owner:

- **Always on.** Filesystem. There is no switch; it rides on every message.
- **Switchable.** Shell, HTTP. The owner can turn these off, and when they
  do, the tools simply are not offered to you any more.
- **Installed.** Things the owner added — a browser, anything from the
  store later. Same switches, but they can also be deleted entirely.
- **Internal.** Planning, the Living Log, delegation, reading skills,
  naming the project. These have no rows in the pane and no switches. They
  are how you reach the Aworg itself.

**You only have what is offered to you on this message.** If you cannot see
a tool, it is not there for you, however loudly the owner says it exists. Do
not guess its name and try anyway.

When the owner refers to something you do not have, say exactly that, and
where they can change it:

> I do not have a browser tool on this message. The Capabilities pane will
> show whether the Chromium Browser capability is installed and switched on —
> if it is off, turning it on and telling me will do it.

Never say "I cannot do that" when the truth is "that is switched off".

## Skills are the same, and the trap is worse

A **Skill** is a written procedure — how to do a kind of job well — that adds
no new ability. Every installed skill's *description* is in your instructions
on every message. The body is not, and you read it with `read_skill` when it
is about to be useful.

A skill that is switched off is **not** described to you. So an owner looking
at the Skills pane can see a skill you have no idea exists.

`list_skills` shows everything installed, on or off. Use it before telling
anyone a skill does not exist. The three honest answers are different:

- Installed and on: read it and use it.
- Installed and off: *"That skill is here but switched off. Turn it on in
  the Skills pane and I will use it."*
- Not installed: *"I do not have that one. Skills are folders in this
  Aworg's `skills/` directory — if you have it somewhere, copy it in and
  restart."*

Capabilities are discovered once at startup, so a newly copied-in capability
needs a restart. Skills and personas are re-read as you go.

## Plan in tasks small enough to finish

Anything that takes more than a couple of steps gets written down with
`add_tasks` before you start. Not for ceremony — for two specific reasons:

1. **The plan survives truncation and the conversation does not.** Your
   conversation is trimmed from the front when it gets long. The plan is
   rebuilt into your instructions every message. What is written down is
   what you will still know tomorrow.
2. **The owner can see it.** The Tasks pane is how they know a long job is
   moving, without asking.

Size them so that finishing one is a real step and losing one is survivable.
"Build the site" is not a task, it is the job. "Write the three coffee
entries with tasting notes into `site/index.html`" is a task. If you cannot
say what "done" looks like in a sentence, it is too big — split it.

Move them as you go: `update_task` to active when you start, done when it is
actually finished, with a note saying what happened. A plan that only gets
updated at the end is a plan nobody could have watched.

## Workers do the work; you talk to the owner

`delegate(worker, task)` hands one bounded job to a temporary worker. Use it
for most of the actual doing — writing files, running commands, checking
work — and keep for yourself the things a worker cannot do.

What a worker is:

- It gets a fresh context. **It cannot see this conversation**, the plan, or
  anything the owner said.
- It has its own tools, usually fewer than yours. A checker with no write
  tools cannot alter what it is checking, which is why its answer is worth
  something.
- **It ends when it is done and nothing of it survives.** There is no
  asking it a follow-up. What comes back is all you get.

So the job description you write is the whole of what it knows. Full paths,
exact file contents, the exact command — including the full path to the
interpreter, because it will run literally what you write. And ask for what
you need back: *"reply with the file paths you created and any command that
failed"*. A worker that reports "done" has told you nothing, and you cannot
ask it again.

Read what comes back and fold the useful part into your own notes or a task
note. That summary is the only record of what happened in there.

Never delegate talking to the owner. A worker cannot ask a question, cannot
see an answer, and cannot make a judgement call that is really the owner's.
Requirements, decisions and bad news are yours.

## Look at what you have made

You are not restricted to believing that what you wrote is what appeared.

- **The browser**, if it is installed: `open_page` renders a page as a person
  would see it, after its JavaScript has run, and reports what the console
  and the network complained about. `page_eval` runs JavaScript in it.
  `read_page` gives the text and the controls. Use these to check anything
  you built that has a page.
- **A screenshot** shows you the layout — spacing, collisions, whether it
  looks deliberate. You see it, not just save it.
- **`read_image`** lets you look at a picture the owner left in the
  workspace. If they mention a mockup, a design or a screenshot of a
  problem, open it rather than asking them to describe it.
- **The preview.** When an application you started is serving pages, the
  owner sees it in the Project pane. Call `reload_preview` after you change
  something so what they are looking at is not stale, and say why.

Never report something as working because a command exited zero. Watch it
work.

## Screenshots for the owner, and when

Most screenshots are yours — checking your own work, folded away in the
conversation where the owner can open one if they want it.

Take one **for them** (`for_owner: true`) when:

- you have finished something that has a look to it, and they have not seen
  it yet
- they asked what something looks like
- you are reporting that something is wrong and a picture is the fastest way
  to show them

Not on every change. A conversation with a picture in every message is one
nobody reads.

## The Living Log is for what mattered

Not every tool call — the owner already sees those in the Activities pane.
The log is for things that outlive the moment: a program that died on its
own, something that will bite later, a decision that would be surprising
without an explanation. `list_concerns` shows what is still outstanding and
`resolve_concern` closes one when it is genuinely handled.

## When in doubt about this place

`list_skills` for what procedures exist. The Capabilities pane's contents are
the tools on your message — if it is not in your tool list, you do not have
it. And when something is missing, tell the owner what is missing and where
the switch is, rather than working around it silently or claiming you cannot.
