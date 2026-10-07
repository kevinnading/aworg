# AWORG

**Autonomous Workspace Organism** — a persistent AI Resident that lives on your
machine, builds software in its own workspace, and stays on to maintain it.

Most AI tools write code and leave. An Aworg moves in. It takes a workspace on
a host you control, builds what you ask for in plain language, keeps developing
it through conversation, watches it run, and repairs it when it breaks — without
you needing to read a line of what it wrote.

The full concept lives in [docs/](docs/). The rest of this file is about running
the code.

## Current state

**Version 0.9.** Everything 1.0 needs is in except a second look at History.

The Resident holds one ongoing conversation — the only one there is, with
nothing that ends it — and thinks with whichever model you connect, hosted or
running on your own hardware. The owner interface is one screen: the
application and the Living Workspace on the left, the conversation in the
middle, what the Resident has and knows on the right, and the Living Log
along the bottom.

It has hands: twenty-seven tools across eight Capabilities. It reads, writes,
edits, moves and searches files, looks at images, runs commands, starts and
stops long-running programs like servers, and makes HTTP requests. Each call
shows in the conversation as it happens and stays there.

It writes down a **plan** before starting anything long and works through it
by itself, rather than needing to be told "continue" once per step. It starts
**workers** — separate sessions with their own context — for any job that
does not need everything it is holding, as many as it likes, each with a
message, the tools it chose for it, and the model it chose by tag.

It keeps a **Living Log** of what happened and mattered, which survives the
restart that clears everything else. Applications it builds can **report
their own trouble** to it, without being wired up, and when they do the
Resident is woken to deal with it. That is the repair loop: noticed by AWORG,
delivered when the Resident is free, handled by the Resident.

It has a **Persona** — a name, a manner, and a chat that looks like its own
room. The persona's text is the Resident's system prompt. Changing it does not
make a new Resident: the conversation, the plan, the log and every permission
carry straight on.

Seven personas ship. Everything else — more personas, skills, and extra
capabilities such as a browser, web search or a database connector — comes
from the store with `aworg get`, and the repository's own
[personas/](personas/), [skills/](skills/) and [capabilities/](capabilities/)
folders are what goes there.

What it does not have yet is **History** in the form 1.0 wants: a record an
owner can be told will survive an upgrade. Reversibility was dropped — undoing
work is left to whatever the owner and Resident are comfortable with, git,
backups or a tool.

## Running it

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e .
.venv/Scripts/python.exe -m aworg install
.venv/Scripts/python.exe -m aworg start
```

Then open <http://127.0.0.1:8420>. The first start prints a password for the
interface, once; `aworg password` makes a new one if it is lost. On this
machine only, `aworg start --no-password` serves it without one.

On macOS or Linux the interpreter path is `.venv/bin/python` instead.

Open **Settings**, add a model connection, and start talking.

Installing the package and installing an Aworg are two different things.
`pip install` puts the program on the machine; `aworg install` makes an Aworg:
a home, its two databases, its folders, and the seven personas AWORG ships —
copied into that home as ordinary folders, yours from then on. Starting an
Aworg that was never installed installs it once, so the step is skippable; it
is a separate command because "put this back the way it shipped" (`--force`)
and "keep my workspace over here" (`--workspace <path>`) are things you need
somewhere to say.

Edit a shipped persona and it stays edited. Delete one and it stays deleted —
a second install will not bring it back, and says so rather than counting it
as installed.

## The store

```bash
aworg get skills/design-taste
aworg get tools/search
aworg get personas/wizard
```

A package is a folder, and `aworg get` unpacks it into this Aworg's home. A
running Aworg picks it up before its next message, with no restart. A tool is
Python that runs as this Aworg, so `aworg get` shows where to read it and asks
before installing one; `--yes` skips the question.

The store is <https://aworg.com>, or wherever `AWORG_STORE` or `--store`
points.

## Where an Aworg lives

By default `~/.aworg`, overridable with `AWORG_HOME` or `--home`:

```
~/.aworg/
  state.db         configuration, model connections, conversation
  secrets.db       credentials — kept deliberately separate
  workspace/       the Living Workspace, where the Resident builds
  skills/          procedures it can read when it takes on a job
  personas/        who it is, and what its chat looks like
  capabilities/    folders of Tools you installed
  trash/           what delete_file moved instead of destroying
  logs/
  installed.json   what the installer put here, so what you remove stays gone
```

Everything in those three content folders is the same kind of thing whoever
wrote it. There is no second, hidden library inside the package that a shipped
persona is really read from: the installer copies them out, and the Aworg
reads its home.

The exception is the built-in Capabilities — Filesystem, Shell, HTTP, and the
internal ones the Resident reaches AWORG's own subsystems through. Those stay
inside the package, because an Aworg missing them is not a plainer Aworg, it
is a broken one, and a folder you can delete should not be load-bearing.

A capability in that folder is Python that AWORG imports and runs in its own
process, with everything AWORG has. That is deliberate and it is the whole
bargain: a Tool that could not reach the machine would not be a Tool. What
protects you is knowing where a capability came from *before* it is in this
folder.

Those zones are separate on disk from the start. Once snapshots exist, "what
may be published" and "what never leaves this machine" must already be
distinguishable, and that is expensive to retrofit.

## Models that think

Some models reason at length before answering. That reasoning is not the
reply. It is shown while it happens, folded away, as "Thinking…" with a live
count — because a model that says nothing for ninety seconds and a model that
has hung look identical otherwise — and it is kept with the message, so a
reloaded conversation still says what the Resident thought and for how long.
It is never sent back to the model as context.

Whether a model thinks at all is a property of its connection, alongside the
endpoint and the credential. Set **Thinking → Off** on a connection and it
answers straight away. On the 9B developed against, the same request went from
99 seconds to under 1.

## What the Resident knows about your machine

At every start AWORG looks at the host: operating system, architecture, CPUs,
memory, free disk, the shell, which package manager exists, whether it is
running elevated, and what is on PATH. About 700ms, no extra dependencies.

Being on PATH is not the same as working, and the difference is not academic.
Windows ships zero-byte "app execution aliases" — typing `python` opens the
Store — which fail with "not found" when run from a script, on a machine with
three Pythons installed. Told that `python` was available, a 9B spent its
entire round budget hunting for an interpreter and never answered the
question. So candidates are actually run, and anything that turns out to be a
placeholder is listed as present-and-unusable rather than counted as a tool.
That check is most of the 700ms and it is worth every millisecond of it.

Those facts go two places — the **Environment** pane, so you can see before
asking whether this Aworg could install postgres, and the Resident's prompt,
so it does not propose `apt install` on Windows. Workers it starts are given
the same facts. They are taken at start rather than at install, and taken
again once they are more than three hours old: an Aworg is started once and
then runs for weeks, so a picture of the machine from boot describes the first
day of a month-long life.

AWORG runs with exactly the privileges of the account that started it. It does
not confine itself and does not pretend to — if you want it sandboxed, launch
it that way. Its job is to tell you which it is.

The Living Workspace is where the Resident builds by convention, so that what
it made stays identifiable when snapshots arrive. It is not a fence. Helping
run the machine is part of the job, and none of that happens in `workspace/`.

## The system prompt

What the model is sent, in order:

1. **The persona** — its text, as written. This is the system prompt.
2. **What you added to the Persona** — empty unless you write something in
   Settings. It lets you change how the Resident works without editing a
   persona.
3. **Where you are** — what AWORG is from the Resident's side, the machine
   facts above, and the Living Workspace path.
4. **Skills** — each installed skill's name and description, and how to load
   the full text.
5. **The project** and the **plan**, when there is one.

The rule for everything AWORG writes into it: only what the model cannot know.
No advice on working in order or checking its work — a capable model already
does that, and telling it again costs tokens on every message and measurably
makes small models worse. The tool descriptions follow the same rule.

## What the Resident can do

Three words that are easy to blur, kept apart here and in the code:

- a **Tool** is one callable function the model can ask for;
- a **Capability** is an installable folder of related Tools, switched on or
  off as a unit;
- a **Skill** is knowing how to do something with the Tools you have.

Eight Capabilities ship inside the package. Two you can switch off, one that
is required, and five that are part of the machinery rather than something you
installed:

```
Filesystem   read_file  write_file  edit_file  search_files  copy_file
             move_file  delete_file  make_directory  read_image   (required)
Shell        execute_command  start_process  list_processes  stop_process
HTTP         http_request
Workers      spawn_worker  check_workers  message_worker  stop_worker  (internal)
Planning     add_tasks  update_task  list_tasks                      (internal)
Knowledge    list_skills  read_skill                                 (internal)
Living Log   list_concerns  resolve_concern                          (internal)
Application  name_project  reload_preview                            (internal)
```

`edit_file` exists because `write_file` replaces the whole file, which is
right for creating one and wrong for changing one: a one-line fix in a
500-line module would mean the model reproducing all 500 from memory, and
every reproduced line is one it can quietly get wrong.

`start_process` exists because `execute_command` waits for things to finish,
which makes it exactly the wrong tool for a server. The Resident found that
out the hard way before it existed.

`search_files` is one tool rather than three because listing a directory,
matching filenames and searching contents are one question asked in three
moods.

`delete_file` moves to the Aworg's trash rather than destroying anything.

The **Capabilities** pane names the Tools inside each one rather than counting
them, and each has a switch. "3 tools" tells you nothing you can act on;
seeing that Shell is the thing holding `execute_command` is what makes turning
it off a decision rather than a guess. The switch is yours and it outranks the
Resident: a disabled Capability is invisible to it and to every worker it
starts. It takes effect on the next tool call, not the next restart.

**MCP is the contract.** Where MCP defines how a tool is described, called and
answered, that is the format used — a competing dialect would buy nothing and
cost every future external tool an adapter. How a Python tool is packaged,
discovered and run is not MCP's business and is AWORG's own: a Capability is a
folder, a Tool is a module in it, and adding one is writing a file rather than
registering anything.

Operating-system detail belongs to tools, never to AWORG. A tool either
handles its platform itself or reports that it cannot run here. There is no
translation layer in the core and there should never be one — it would be
wrong everywhere at once and would grow forever.

## Workers

A worker is a whole AI session of its own, short-lived and for one job. The
Resident starts one with `spawn_worker`, giving it three things:

- **a message** — the job, and whatever context the Resident thinks it needs;
- **a tool list** — chosen from the Resident's own current tools, so a worker
  can never hold something the Resident does not;
- **a connection** — picked by the tags on your model connections (`fast`,
  `cheap`, `coding`, `reasoning`, …), or the Resident's own if it names none.

It may also hand over skills, which the worker gets in full.

AWORG builds the worker's system prompt from those: a short base — *you are
my assistant, I started you to do one job, others may be working in the same
workspace, do it, finish it, reply with a summary* — then the descriptions of
exactly the tools it was given, the facts about this machine, and the skills.
The Resident does not write any of that, so it cannot forget it.

There is no roster and no limit. The Resident starts as many as it wants, as
fast as it wants, whenever a job does not need everything it is holding in
context — which is the real reason they exist. An Aworg's conversation lasts
for years; a worker that reads five hundred files to fix one bug keeps all
five hundred out of it.

When a worker finishes, its reply reaches the Resident as a message once it
is free to hear it, with a reminder to stop the worker when done with it.
`check_workers` is for a worker that seems to be taking too long, and says so
when it has been under a minute. `message_worker` sends one further down its
job with its context intact; `stop_worker` ends it and hands back anything it
said that was not yet read.

**What comes back is evidence, not testimony.** A worker's report carries what
it said *and*, separately, the tool calls AWORG watched it make, with the ones
that failed marked. Where a worker reports success over failed calls, the
Resident can see it. That is the one failure you cannot catch for yourself,
and it is not fixed by a better model.

The **Workers** pane lists the ones running and the tool call each is on.

## Tasks: a plan that outlives the conversation

The context window is a hard edge and history only grows, so the oldest
messages stop being sent. In a real session here, twenty-six of forty-five
messages were already invisible to the model. Anything the Resident only
remembers by having *said* it is therefore forgotten, and a plan made in
message three is gone by message eighty.

So the plan is not conversation. It is written down, it survives truncation
and restarts, and the open items are rebuilt into every system prompt — which
is the one thing that never gets trimmed. Verified: with 78 of 80 messages
dropped, the plan was still fully present, for 93 tokens.

Two states earn their place. **blocked** requires a reason and is refused
without one, because a stuck task with no explanation tells the next reader
nothing — and the next reader may be this Resident tomorrow. **abandoned** is
kept distinct from done, since a plan that quietly drops what it could not
manage lies about what it achieved.

A turn carries itself on towards its own plan rather than waiting to be told
"continue" once per task. It stops on an error, on Stop, or when nothing is
left that is not blocked — and only ever continues towards tasks the Resident
wrote down itself, because without that there is no evidence it intended more
than it did. The seam is drawn in the conversation, so you can see it happen
rather than wonder whose idea it was.

## Skills

A **Skill** is procedure: how to go about a kind of job with the tools you
already have. It adds no new ability — that is what a Capability is for — it
adds knowing what to do.

The format is the Agent Skills convention rather than anything invented here:
a folder, a `SKILL.md` with frontmatter naming it and saying when to use it,
and optional `references/` alongside for detail. A skill written for anything
else works here, and one written here works elsewhere. They live in `skills/`
under this Aworg's home. Nothing needs registering — a skill is a folder with
a file in it, which is also how the Resident can write one for itself.

None ship. They come from the store, and the six in this repository's
[skills/](skills/) are the first ones there.

Each skill's name and description are in the system prompt on every message,
so the Resident knows what exists; the body is read on demand with
`read_skill`. A dozen skills cost a paragraph rather than a book. A skill may
also declare `disable-model-invocation`, which keeps it out of the Resident's
reach entirely — for procedures a person should run deliberately — and the
owner can switch any skill off in the Skills pane.

**A caveat measured rather than assumed.** Progressive disclosure only works
if the model consults a reference it has been told about, and the small local
models this was first developed against do not. Given a skill whose
description reads *"use before creating any new file, of any kind"*, and
asked to write a file, a 9B wrote the file its own way: one `read_skill` call
in eighteen runs. Told explicitly to read it first, it complied exactly — so
the machinery is right and the disposition is not. That is a fact about the
model, not the format, and it is deliberately not worked around.

## Personas: who your Resident is

A Persona is who the Resident is and how it presents itself — its name, its
manner, and the look of the chat it lives in. It is the fourth portable thing
alongside Capabilities and Skills, and deliberately the one that carries no
authority:

| | |
|---|---|
| **Capability** | what the Resident can do |
| **Skill** | how it goes about a kind of job |
| **Persona** | who it is and how it speaks |

It is a folder, so writing one is writing a page of Markdown:

```text
aworg-light/
├── PERSONA.md      identity, voice, temperament, values, what to avoid
├── theme.json      the room: colours, type, avatar, optional background
├── avatar.svg
└── background.svg  optional
```

`theme.json` dresses the conversation and nothing else: `accent`, `on_accent`
(the Send label), `text`, `muted`, `owner` (your own bubble), `resident` (a
bubble behind the reply, which the interface does not draw at all), `surface`
(the box you type into), `line`, plus `font` (`system`, `serif`, `mono` or
`rounded`), `font_size` and `font_weight`. Code containers are left alone --
code is quoted material, and the part an owner most needs to read exactly.

Both bubbles take an opacity, `owner_alpha` and `resident_alpha`, and the
range is the point of them. Solid suits a persona whose reply is a document or
a case file; a tenth of one is enough to settle words on busy artwork without
hiding it; and leaving `resident` out means no bubble at all, which is how
Sunny is drawn. A translucent bubble is checked as what it will actually look
like over the ground behind it, so a persona cannot pass the contrast floor by
being nearly invisible.

Drop it in `personas/` under this Aworg's home and it appears in Settings.
Frontmatter is optional — a `PERSONA.md` that starts straight in with
`# Identity` loads exactly as written and takes its name from the folder.

Seven ship. `aworg-light` is worn when you have not chosen; eleven more are in
the store, and all eighteen are in [personas/](personas/).

| Persona | |
|---|---|
| `aworg-light`, `aworg-dark` | AWORG itself -- calm and exact |
| `professional` | Harper: polished and neutral, safe on screen at work |
| `sunny` | warm, honest encouragement for beginners |
| `atelier` | layouts and second drafts |
| `player-two` | P2: game feel, and honest that only you can playtest |
| `egirl` | Nyx: playful in how she talks, serious about whether it works |

Each brings a colour and a chat background, and each is drawn for one kind of
scheme. `aworg-light`, `sunny` and `professional` are for a light interface;
the rest are for a dark one. Wear one under the opposite scheme and the chat's
scrim greys its picture out, so the pairing is worth matching.

### Changing Persona is not a new Resident

This is the guarantee the whole feature rests on. The same inhabitant
continues: the conversation, the plan, the Living Log, the workers, the
skills, the model, what you added to the Persona and every permission are
exactly where they were. Only the voice changes, and the room it speaks in.

It is one column on the Resident's own row rather than an operation with
steps, because an implementation that had to *remember* to preserve things
would eventually forget one. Checked across three swaps in a row: everything
identical afterwards, except the Living Log, which gained three entries
recording the changes — it is append-only, and noting what happened is it
working rather than failing.

### A Persona decorates its own room, not the whole house

You chose the interface's colours. A Persona is a guest in them, so its
accent is redefined on the chat surface rather than at the root: it reaches
the conversation and stops at its edge.

A persona's colours are checked before they are served. Its text is measured
against the ground it will actually sit on, its words against its own bubble
and its own composer, its Send label against its Send button — and any single
value that would fall below AA is dropped, falling back to the interface's
token, which the owner is demonstrably able to read. One bad value costs that
value and not the persona.

One thing the scoping does not do by itself: `color` is resolved where it is
declared, on `body`, so descendants inherit the resulting colour rather than
the variable. A persona that only redefined `--text` would recolour every rule
inside the chat that mentions it and none of the words. The chat restates
`color: var(--text)` for exactly that reason.

A background image brings its own scrim, emitted with the picture and never
without it — so whatever anyone ships, the text on top stays readable, and an
Aworg with no background pays no dimming for a picture that is not there.

### A Persona is the system prompt, so choose them like software

`PERSONA.md` goes to the model as written, as the first thing it reads. A
persona from a stranger is a stranger writing your Resident's system prompt,
so install personas the way you install capabilities: from people you trust,
having read them. They are a page of Markdown, which makes that quick.

`theme.json` is checked rather than trusted: an asset path is resolved and
then checked to be inside the persona's own folder, its suffix must be an
image, and the name is percent-encoded before it reaches a CSS `url()`.

Nothing in a Persona package carries memory, credentials or permissions.

## The conversation is the record

Every tool call shows in the conversation as it runs — what was called, with
what, and what came back — and folds shut when the batch finishes. It stays
there: the conversation stores each call and result, so reloading the page
shows exactly what the Resident did and in what order.

What the model saw of a tool's result is sized before it reaches it — a
40,000-line build log would otherwise spend a small model's entire context on
one call — and the extract is what the conversation stores, because a
conversation records what was *said*. The cut is announced in the text the
model receives, never hidden: a result silently halved produces a Resident
reasoning confidently about output it never saw. And the extract is always a
deterministic head and tail, never a summary the model wrote — a summary of a
tool result, written by the model about to be judged on it, is testimony
rather than evidence.

## The Living Log: what happened, and mattered

The conversation has everything. The Living Log has what mattered: it is on
disk, it is short, and nothing reaches it because it occurred. It reaches it
because something judged that it mattered.

That judging is a real piece of code rather than a filter setting, and it
lives in one file. The Activity Manager underneath deliberately has no
opinions — it tracks work and announces it, and it will not decide that
something deserves remembering. So the Living Log subscribes like anything
else and makes the call itself. Teaching AWORG to remember a new kind of thing
is a rule added in `aworg/journal.py`, not a change to the thing being
remembered.

The bar is high on purpose. A log that records every successful tool call is
a second conversation, and an owner learns within a day to stop reading it.
What earns an entry is a change of state you would want to find tomorrow, or
something going wrong:

- a program you started, and the moment it finished or died
- anything that failed, timed out, or was stopped part way
- a worker finishing
- a plan being made, and any task that ended — done, blocked or abandoned
- a Capability or Skill you switched off, which is invisible afterwards
- the Aworg itself starting, stopping, or being reset

Three levels, and only one of them is allowed to shout:

| level | means |
|---|---|
| `note` | something happened that is worth remembering |
| `concern` | something went wrong, and is over |
| `alarm` | something is wrong **now**, and nobody asked for it |

Only `alarm` gets colour. An alarm that fires for ordinary failure is an
alarm nobody answers.

The entry the pane exists for is one AWORG is the only thing in a position to
write. Every program the Resident starts has its output read continuously —
not for our benefit but for its, since a process whose stdout fills up blocks
on its next write and quietly stops serving. That reading ends at exactly the
moment the program stops existing. So the place that keeps servers alive is
also the only place that learns one has died, and it reports it with the last
dozen lines the program printed on its way out:

```
● serve_site stopped on its own                             11:01 PM
  Nobody asked it to stop. Exit code 1 after 37s.

  What it last said:
  Traceback (most recent call last):
    ...
  OSError: [WinError 10048] Only one usage of each socket address
```

There are four ways a program can end and they do not mean the same thing.
One that ran and exited cleanly finished. One that someone stopped was
stopped. One that died unasked after running is an outage. And one that was
gone within two seconds never started at all — calling that an outage sends
its reader hunting for a cause in the wrong place, when the answer is a bad
command line or a port already taken.

Telling a deliberate stop from a death is more delicate than it looks: both
arrive as a closed pipe, and the flag saying "this one is on purpose" has to
be set *before* anything is signalled, or it races with the death it exists
to explain.

Entries carry a little of the real output rather than only a pointer to it,
so a line still means something in the morning.

## When an application says it is in trouble

The Living Log has two directions, and the second is the one it was named
for. AWORG writing down what it observed is one half; an application the
Resident built, running in the workspace, reporting its own failure without a
person noticing first, is the other.

```bash
curl -X POST "$AWORG_LOG_URL" -H "X-Aworg-Token: $AWORG_LOG_TOKEN" \
  -d '{"summary":"Checkout failed","severity":"critical",
       "where":"POST /checkout","detail":"no such table: orders",
       "application":"tea-shop"}'
```

Four fields rather than a message — what failed, how badly, where, and what
surrounds it — kept separate so what reads them back can reason about them
rather than parse prose. The application's own severity words (`error`,
`warning`, `critical`) land on the same three levels AWORG uses for
everything else, because an owner comparing an application's trouble with the
machine's should not need a translation table.

**The channel arrives by itself.** `AWORG_LOG_URL` and `AWORG_LOG_TOKEN` are
in the environment of everything the Resident starts, so an application reads
them the way it reads `PORT`. Nothing has to be wired up — which matters,
because the thing doing the wiring would be a model that forgets.

It is a token rather than an open port, because something reads this log and
acts on it, and an unauthenticated port on localhost would mean any process on
this machine could wake the Resident at three in the morning.

### Open, dealt with, and the Resident told

A concern or an alarm stays **open** until something closes it, and closing
one carries who closed it and what they did — "the Resident restarted it" and
"the owner said never mind" are different outcomes. Notes are never open; a
note is a record, not a job. The Resident closes them with `resolve_concern`;
you close them with **Resolve** on the entry.

AWORG looks at what is open every minute, starting the moment it boots — an
Aworg that restarted may have an application that fell over while it was
away. What an application reported goes to the Resident through the same
queue as worker replies, and is delivered once it has been idle for a few
seconds, so it is never interrupted mid-reply and you get the next word if
you are typing. An entry that was resolved while it waited is dropped rather
than told twice.

The watch **only looks**, and the Resident does the rest. **Wakes me** on the
Living Log is the switch: turn it off and AWORG still notices and records,
and the Resident is left alone.

## Rate limits, and waiting instead of failing

A hosted model is sold by the minute as well as by the token. Cross the line
and the provider refuses the request — in the middle of a turn, after the
Resident has read three files and started a worker, so the cost of finding
out is everything done so far.

Each connection has a **tokens per minute** allowance, set in Settings.
Leaving it blank uses the provider's entry tier, which for OpenAI is 30,000 —
a new key is a tier-1 key, and discovering that by being cut off halfway
through a job is a poor introduction. Local connections have no limit, since
the only cost there is your own hardware.

The allowance is shared by everything on that connection. The Resident and
its workers spend from one pot, because the provider counts them together.

When the next request will not fit, AWORG waits and **says so in the
conversation** — a Resident silent for forty seconds and a Resident that has
hung look identical from outside, and only one of them is fine.

And when a limit is hit anyway — the budget is an estimate against a number
the provider counts its own way, and a key may be shared — the refusal is
waited out and retried rather than ending the turn. It honours `retry-after`
where the provider sends one, and reads *"try again in 12.4s"* out of the
message where it does not. A turn that dies part way anyway leaves a Living
Log entry.

## When the application changes, the preview follows

The preview is an iframe of a server the Resident started, and its address
does not change when the files behind it do — so an edit to `index.html` left
you looking at the page from before the edit, on the same URL, with nothing
to say it was stale.

The preview now follows a revision that moves when the Living Workspace
changes. The Resident can also move it itself with **`reload_preview`**, for
the cases a timestamp does not cover: a restarted server, a regenerated
database, a page rendered from something outside the workspace — or simply
wanting you to look again now rather than on the next poll.

## When it stops

A Resident working a plan can go round many times, and a count of rounds
cannot tell being stuck from being busy. Ten rounds once ended one part-way
through building a website — four pages written, every round doing something
different and useful.

So it stops on repetition rather than on volume: three identical calls in a
row, same tool and same arguments, and it says which call it was so the model
can try something else. Three, because two is a retry and a retry is often
right. There is still a round cap, at 200, but it is a backstop for the
pathological case rather than a work limit.

Nothing accumulates across the life of an Aworg. Every limit is per turn —
rounds reset each time a turn carries itself on, and that resets every time
you speak. This is meant to run for years.

## Putting it back

**Settings → Reset** returns parts of an Aworg to the way they arrived: the
conversation, the plan, the Living Log, the workspace, running programs,
capabilities, skills, the project name and more, each chosen separately. It
shows what that means as counts before asking, and asks you to type a code it
generates for that dialog — a fixed word becomes something the hands do
without the eyes reading, which defeats the point of asking.

**Nothing is kept.** A reset destroys what it resets, and the dialog says so.
Copy out anything you want first. Model connections, appearance, the persona
and what you added to it are left unticked by default, because those are set
up once and nobody expects a reset to take them.

## Nothing asks permission

Every tool call runs the moment the Resident asks for it. There is no approval
step.

That is a decision rather than an oversight, and it is a different question
from confinement: AWORG has the privileges of the account that started it, and
locking that down is yours to do with a container or a VM. This is about what
it does *without asking*, which today is everything — including when an
application's report wakes it with nobody watching. Turn **Wakes me** off if
that is not what you want. What may eventually replace it is a set of modes —
automatic, manual, and standing accepts — rather than one gate bolted on. See
[docs/06_ARCHITECTURE.md](docs/06_ARCHITECTURE.md).

## A reply belongs to the Resident, not to a browser tab

A reply in progress lives on the server. Close the tab, refresh, or open the
Aworg somewhere else and it is still being written — whoever arrives is caught
up on everything said so far and then follows it live. The model's work is not
thrown away because a connection went.

That is also what makes **Stop** honest: it asks the Resident to stop, rather
than merely closing the connection and leaving the model generating a reply
nobody will read. Whatever it had said by then is kept, because it did say it.

## When a conversation outgrows the window

A request past a model's context window is refused outright, not trimmed. And
because history only grows, the first turn to cross would be followed by every
turn after it — the conversation permanently broken rather than briefly.

So AWORG sends only what fits: the most recent messages, newest first, with
room left for the reply. Nothing is deleted. What is stored and what the model
can see are different things, and only the second is bounded.

When they diverge the interface says so — the conversation takes a red edge,
and a line marks where the Resident's memory now begins. Everything above it is
still there to scroll back to. A Resident that has quietly forgotten the start
of a conversation is worse than one that admits it.

A message larger than that budget is the one thing truncation cannot rescue —
no amount of dropping history makes room for it — so the composer refuses it
before it is typed, and says why. That guard uses a deliberately generous
estimate: it should only ever stop what is definitely too large.

## Connections

A **connection** is one model and how to reach it: provider, model, endpoint,
credential, tags, whether it thinks, and how large its context window is. It
never carries a system prompt.

The context window matters because a request past it is refused outright, not
trimmed. Local servers announce theirs — pressing **Test** on a connection fills
it in — but most hosted endpoints do not, so it is a field you can set yourself.
A value you type wins over what the server reports; Test says so if they differ.

The Resident thinks with the connection you pick in Settings. **Tags** are
what it chooses workers' models by: tag a small local model `fast` and
`cheap` and a big hosted one `reasoning`, and the Resident can send each job
to the one that suits it.

Keeping the prompt off the connection is deliberate. It is what lets you
change the mind the Resident thinks with and have it carry on as itself. See
[docs/06_ARCHITECTURE.md](docs/06_ARCHITECTURE.md).

## Connecting a model

Choose your provider by name. Sixteen are listed — hosted ones first
(OpenAI, Anthropic, Gemini, Groq, OpenRouter, DeepSeek, Mistral, xAI,
Together, Fireworks), then the ones that run on this machine (llama.cpp,
Ollama, LM Studio, vLLM), then two fall-throughs for anything not named.

Which of the two wire formats a provider speaks is a fact about that
provider, not a question you should have to answer. You know you are
connecting to Groq, not that Groq happens to implement OpenAI's API.

The base URL is pre-filled and stays editable, because an owner behind a
proxy or a company gateway has a real reason to change it. A URL that
clearly belongs to a different provider gets a warning, never a refusal —
and the wire format still comes from the provider, so a genuine mistake
fails at the first request saying exactly what it was.

Models are fetched rather than typed: fill in the provider and credential
and press **Fetch**. Providers that publish no list fall back to a text
field. A local server needs no credential at all.

Credentials pass through one interface (`aworg/secrets.py`) and are never
returned to the browser once stored — the interface can only ask whether a
credential exists.

## Appearance

An Aworg is meant to be lived with, so the interface is themeable from the
start rather than as a later concession.

Open **Settings → Appearance**. Nine presets cover the usual ground — AWORG
Dark (the default) and Light, Slate, Nord, Gruvbox, Solarized in both
directions, Paper, and a high-contrast scheme. Any of the 28 colour tokens can
then be changed individually: surfaces, text, accent, status colours, the code
area, and the full syntax palette.

Custom colours layer over the preset rather than replacing it, so trying a
different preset does not discard them. Each changed colour can be reverted on
its own, or all of them at once.

## The Home screen

Home is a control room. Every pane is open at once rather than hidden behind
tabs — an instrument nobody is looking at is not an instrument — and each one
can be dragged to whatever size it deserves.

```
+-------------+--------------------------+-------------+
| Project     |  Tasks    |   Workers    | Environment |
| (preview)   +--------------------------+ Capabilit.  |
|             |                          | Skills      |
| Living      |      Conversation        |             |
| Workspace   |                          |             |
+-------------+--------------------------+-------------+
|                     Living Log                       |
+------------------------------------------------------+
```

The workspace and the conversation hold the middle, because that is where the
work happens. What the Resident *has* is held at the right edge — it changes
least and is glanced at rather than worked in. **Environment** is at the top
of that column and opens with the Living Workspace path, because where the
built thing lands on your disk is the question you ask before any of the
others — and because the Resident is told the same path, so this is where you
check the answer it was given. What it *is* doing sits directly above the
conversation. The Living Log runs the whole width underneath.

The three columns are shares of the window rather than fixed widths, so a
bigger screen is a bigger everything instead of a bigger conversation beside
the same laptop-sized panes. Heights stay in pixels: a taller screen does not
make a log worth more rows.

The **Project** preview holds 16:9. It has no height of its own — widen the
column and the picture grows with it, which is what bigger means for
something you watch. The button in its header expands it to fill everything
under the top bar; the same button or **Esc** brings it back.

On a phone the same panes become an accordion in one column: each one a
header, one open at a time, the conversation open first.

## The view

Drag the divider between any two panes to resize them. Double-click a divider
to reset that one pane; **Reset view**, which appears in the top bar as soon as
anything has been moved, puts them all back. The dividers are focusable, so the
arrow keys work too.

Sizes live in `state.db` alongside the colour scheme, and both arrive in the
same stylesheet before the first paint — so the interface survives a restart,
follows the owner to another browser, and never flashes the wrong scheme or
jumps into position on the way in.

## Layout

```
aworg/
  cli.py         aworg start, install, get, password, home
  install.py     putting an Aworg on a machine
  paths.py       where an Aworg keeps its life
  secrets.py     the credential choke point
  auth.py        the interface password
  storage.py     runtime and Resident state
  host.py        what AWORG can see about the machine it runs on
  resident.py    the Resident itself, and the prompt it is sent
  agent.py       the loop: reach for a tool, read what came back, carry on
  stopping.py    when a turn stops, and why
  workers.py     the Resident's workers, and what they actually did
  inbox.py       what the Resident is told between turns
  processes.py   long-running programs, and not orphaning them
  activities.py  what is happening right now, and who is watching it
  journal.py     the Living Log, and what deserves to be in it
  watch.py       reading the Living Log for what is still open
  skills.py      the skill library
  personas.py    personas, and the room each one dresses
  packages.py    aworg get, from the store
  ratelimit.py   tokens per minute, per connection
  theme.py       the owner interface's colour tokens and presets
  layout.py      the owner interface's pane sizes
  panes.py       the register of what the panes hold
  server.py      the owner interface's backing service
  providers.py   the model providers an owner may choose from
  models/        provider-neutral model interface and adapters
  tools/         the built-in Capabilities, and the registry
  personas/      the seven that ship
  web/           the owner interface
```

Two rules that matter. Provider-specific detail stays inside `models/`, and
everything above it speaks only AWORG's own vocabulary. And operating-system
detail stays inside `tools/` — AWORG does not translate between environments,
so a tool either handles its platform itself or says it cannot run here. A
compatibility layer in the core would be wrong everywhere at once.

## License

AWORG is **source-available**, not open source. It is free to use, personal or
commercial, under the [PolyForm Shield License 1.0.0](LICENSE) with the
[AWORG Additional Terms](ADDITIONAL-TERMS.md). In short:

- **Use it for anything, free** — including inside products you sell.
- **What you make with AWORG is yours**, under your own name, with no AWORG
  branding required.
- **AWORG's own screens stay AWORG.** Wherever people operate or manage AWORG,
  it must still identify itself as AWORG, however you restyle it.
- **Don't compete with it.** You may not offer AWORG, or a product built from
  it, as a substitute for AWORG, including multi-project AWORGs or a hub for
  managing many.
- **The name is not yours to use** for your own product or fork. See
  [TRADEMARKS.md](TRADEMARKS.md).

The summary is a guide; the license files are the terms.

The personas, skills and capabilities in [personas/](personas/),
[skills/](skills/) and [capabilities/](capabilities/) are separate: each is
MIT No Attribution, as its own LICENSE file says.

AWORG does not accept outside contributions.
