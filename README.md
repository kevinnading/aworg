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

**The Resident is present, legible, and can act.**

It holds one ongoing conversation — the only one there is, with nothing that
ends it — and connects to whichever model you choose —
hosted, or one running on your own hardware. The owner interface is one screen:
the application area and Living Workspace on the left, the conversation down the
right. Replies render with syntax highlighting, and the workspace listing
follows along as it changes.

It has hands: thirteen tools across five Capabilities. It reads, writes, edits
and searches files, runs commands, starts and stops long-running programs like
servers, and makes HTTP requests. What it is doing shows up in the
**Activities** pane as it happens.

It writes down a **plan** before starting anything long, and works through it —
carrying on by itself rather than needing to be told "continue" once per step.
It hands bounded work to **workers**, specialists with their own prompt, their
own narrow set of tools, and their own **skills** — this machine's conventions
put in front of them rather than left to be asked for.

Asked for a three-page website, it plans the work, delegates the writing,
starts a server, checks the pages actually answer, and shows you the running
site in the Application pane.

It keeps a **Living Log** of what happened and mattered, which survives the
restart that clears everything else — including the one entry nothing else in
AWORG can produce: a program that stopped on its own, with what it last said
before it went.

It has a **Persona** — a name, a manner, and a chat that looks like its own
room. Changing it does not make a new Resident: the conversation, the plan,
the log and every permission carry straight on.

Applications it builds can **report their own trouble** back to it, without
being wired up: the channel arrives in their environment. AWORG reads that
log every minute and holds what is still outstanding.

What it does not have yet is the autonomous repair loop — the part that takes
what the watch found at three in the morning and does something about it —
and History and Reversibility. See
[docs/02_MVP_SPEC.md](docs/02_MVP_SPEC.md).

## Running it

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e .
.venv/Scripts/python.exe -m aworg start
```

Then open <http://127.0.0.1:8420>.

On macOS or Linux the interpreter path is `.venv/bin/python` instead.

Open **Settings**, add a model connection, and start talking.

## Where an Aworg lives

By default `~/.aworg`, overridable with `AWORG_HOME` or `--home`:

```
~/.aworg/
  state.db      configuration, model connections, conversation
  secrets.db    credentials — kept deliberately separate
  workspace/    the Living Workspace, where the Resident builds
  logs/
```

Those zones are separate on disk from the start. Once snapshots exist, "what
may be published" and "what never leaves this machine" must already be
distinguishable, and that is expensive to retrofit.

## Models that think

Some models reason at length before answering. That reasoning is not the
reply: it is never saved, never sent back as context, and never shown as
something the Resident said. It *is* shown while it happens, folded away, as
"Thinking…" with a live count — because a model that says nothing for ninety
seconds and a model that has hung look identical otherwise.

Whether a model thinks at all is a property of its connection, alongside the
endpoint and the credential. Set **Thinking → Off** on a connection and it
answers straight away. On the 9B developed against, the same request went from
99 seconds to under 1.

## What the Resident knows about your machine

At every start AWORG looks at the host: operating system, architecture, CPUs,
memory, free disk, which package manager exists, whether it is running
elevated, and what is on PATH. About 700ms, no extra dependencies.

Being on PATH is not the same as working, and the difference is not academic.
Windows ships zero-byte "app execution aliases" — typing `python` opens the
Store — which fail with "not found" when run from a script, on a machine with
three Pythons installed. Told that `python` was available, a 9B spent its
entire round budget hunting for an interpreter and never answered the
question. So candidates are actually run, and anything that turns out to be a
placeholder is listed as present-and-unusable rather than counted as a tool.
That check is most of the 700ms and it is worth every millisecond of it.

Those facts go two places — the **Capabilities** pane, so you can see before
asking whether this Aworg could install postgres, and the Resident's context,
so it does not propose `apt install` on Windows. They are taken at start
rather than at install, and taken again once they are more than three hours
old: an Aworg is started once and then runs for weeks, so a picture of the
machine from boot describes the first day of a month-long life.

AWORG runs with exactly the privileges of the account that started it. It does
not confine itself and does not pretend to — if you want it sandboxed, launch
it that way. Its job is to tell you which it is.

The Living Workspace is where the Resident builds by convention, so that what
it made stays identifiable when snapshots arrive. It is not a fence. Helping
run the machine is part of the job, and none of that happens in `workspace/`.

## What the Resident can do

Three words that are easy to blur, kept apart here and in the code:

- a **Tool** is one callable function the model can ask for;
- a **Capability** is an installable folder of related Tools, switched on or
  off as a unit;
- a **Skill** is knowing how to do something with the Tools you have.

Five Capabilities. Three you can switch, and two that are part of the
machinery rather than something you installed:

```
Filesystem   read_file  write_file  edit_file  search_files
Shell        execute_command  start_process  list_processes  stop_process
HTTP         http_request
Delegation   delegate                                    (internal)
Planning     add_tasks  update_task  list_tasks          (internal)
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

The **Capabilities** pane names the Tools inside each one rather than counting
them, and each has a switch. "3 tools" tells you nothing you can act on;
seeing that Shell is the thing holding `execute_command` is what makes turning
it off a decision rather than a guess. The switch is yours and it outranks the
Resident: a disabled Capability is invisible to it, and to any worker it
spawns, whatever that worker was handed. It takes effect on the next tool
call, not the next restart.

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

The Resident can do the work itself or hand it to a specialist. Three ship:

```
builder   writes and edits files          cannot run anything
runner    runs commands, reports output   cannot write files
checker   verifies that something works   cannot change anything
```

A worker is three things — a connection, a prompt, and a **tool scope** — and
the third does the most work. The checker cannot rubber-stamp by quietly
fixing what it was asked to check, because it holds no tool that writes. That
is not trust; it was not handed the means.

Workers are temporary. One bounded job, no memory of it afterwards, disposed.
Nothing a worker says reaches your conversation directly — only the result the
Resident reads.

**Delegation is one tool with a list of names, not one tool per worker.**
Tool-selection accuracy falls away as the surface grows, so a tool per
specialist would degrade routing the moment you defined a few. One tool keeps
the surface flat however many workers exist. The consequence is that a
worker's *description* is load-bearing: it is the only thing the Resident
routes on, so a vague one is a misrouted job.

**What comes back is evidence, not testimony.** A worker's result carries what
it claimed *and*, separately, what AWORG watched it actually do — which tools
ran, which failed. Where a worker reports success over failed calls, the
result says so. That is the one failure you cannot catch for yourself, and it
is not fixed by a better model.

Their work nests in the Activities pane, so you can see which worker did what
rather than a flat list with no sign of who ran anything.

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
else works here, and one written here works elsewhere. Shipped skills live in
the package; yours go in `skills/` under this Aworg's home, where a name
collision means yours wins. Nothing needs registering — a skill is a folder
with a file in it, which is also how the Resident can write one for itself.

Descriptions are in the system prompt on every message, so the Resident knows
what exists; bodies are read on demand with `read_skill`. A dozen skills cost
a paragraph rather than a book. A skill may also declare
`disable-model-invocation`, which keeps it out of the Resident's reach
entirely — for procedures a person should run deliberately — and the owner
can switch any skill off in the Skills pane.

**A caveat measured rather than assumed.** Progressive disclosure only works
if the model consults a reference it has been told about, and the 9B this is
developed against does not. Given a skill whose description reads *"use
before creating any new file, of any kind"*, and asked to write a file, it
wrote the file its own way: one `read_skill` call in eighteen runs, across
three differently-worded descriptions and with the instruction moved into the
standing prompt. Told explicitly to read it first, it complied exactly — so
the machinery is right and the disposition is not.

That is a fact about the model, not the format, and it is deliberately not
worked around. These small models are a floor for proving the loop holds, not
a target to design for. A model that will not consult a procedure it has been
told about cannot be trusted with an Aworg's conventions, and the answer is a
better model rather than a bigger prompt.

Two ship. `house-style` is the conventions this Aworg writes files by;
`web-project` is how to build and serve a small site end to end.

### Workers are given skills, not offered them

A worker has a skill scope the way it has a tool scope — the owner decides
what it knows, and the Resident cannot widen it at dispatch. The builder and
the checker ship with `house-style`; the runner with none, since it types
what it is told to type.

But a worker does not get descriptions to choose from. It gets the skill
itself, in full, in its prompt, with no decision left to make. Progressive
disclosure solves a problem a worker does not have: it exists so a Resident
carrying a dozen skills across an open-ended conversation pays a paragraph
rather than a book, and a worker is a fresh context for one bounded job
holding the two skills it was scoped to.

The rest is measured. Asked plainly, a local model reaches for a matching
skill about one time in six. Told to read a named one, four times out of
four. The reliable half is *being told* — so the Resident's part is moved to
the thing it is good at, which is routing. `delegate` names what each worker
knows alongside what it does, and choosing the worker that has `house-style`
is a decision from a described list rather than an unprompted act of
initiative.

It is a partial win and worth saying so plainly. On granite-4-tiny, five
runs: putting scripts in `bin/` went from 0/5 to 4/5. Hyphens instead of
underscores went to 1/5, and the provenance line stayed at 0/5. The skill
text is verbatim in the worker's prompt, so those two are the model rather
than the plumbing — `random_tea.py` is what a python file is called in
essentially all training data, and the house rule loses to the prior.

The checker is the answer to that, and it is this project's own argument
applied one level down: a check performed by the thing being checked is
decoration. Given the same skill, the checker caught the missing provenance
line 4 times out of 4 on a file the builder had just written without one. It
cannot judge the naming rule — it recites it and then calls `random_tea.py`
compliant — so it reliably notices something *absent* and cannot evaluate a
property of a string in front of it.

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
├── theme.json      accent colour, avatar, optional chat background
├── avatar.svg
└── background.jpg  optional
```

Drop it in `personas/` under this Aworg's home and it appears in Settings.
Frontmatter is optional — a `PERSONA.md` that starts straight in with
`# Identity` loads exactly as written and takes its name from the folder.

Eighteen ship, so there is one for most people who will ever open an Aworg.
`aworg-light` is worn when you have not chosen.

| For | Personas |
|---|---|
| AWORG itself | `aworg-light`, `aworg-dark` -- calm and exact, reporting what was checked rather than what was hoped |
| Skill level | `teacher` (Ms. Hazel, for people who have never written code), `sunny` (warm and honest encouragement), `greybeard` (terse senior engineer) |
| What you build | `founder` (Sloane: customers, cost, launch), `player-two` (P2: game feel, and honest that only you can playtest), `quill` (words and voice), `atelier` (layouts and second drafts) |
| Setting | `professional` (Harper: safe on screen at work), `nocturne` (the long job you start and walk away from), `scribe` (as plain as a persona gets) |
| Vibe | `egirl` (Nyx), `gamer-bro` (Tank, her duo), `cottagecore` (Bramble) |
| Just for fun | `noir` (Dex Malone, P.I.), `pirate` (Cap'n Barnacle Byte), `wizard` (Ozwald the Compiled) |

Every persona but `scribe` brings a colour and a chat background, and each is
drawn for one kind of scheme. `aworg-light`, `sunny`, `quill`, `founder` and
`professional` are for a light interface; the rest are for a dark one. Wear one
under the opposite scheme and the chat's scrim greys its picture out, so the
pairing is worth matching.

Every one of them holds the same lines, whatever the voice: code, commands,
errors and numbers are written exactly; a failure is never dressed up; and
nothing is called done that was not checked. The characters are not allowed to
promise what AWORG cannot do -- Nocturne says outright that it cannot reach
you while you are away, and P2 that it cannot feel a jump.

### Changing Persona is not a new Resident

This is the guarantee the whole feature rests on. The same inhabitant
continues: the conversation, the plan, the Living Log, the workers, the
skills, the model, your standing instructions and every permission are
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
the conversation and stops at its edge. The app stays your teal while the
chat goes Atelier's amber.

A background image brings its own scrim, emitted with the picture and never
without it — so whatever anyone ships, the text on top stays readable, and an
Aworg with no background pays no dimming for a picture that is not there.

### A Persona is untrusted text

Personas are meant to be downloaded and swapped around, which makes
`PERSONA.md` the one part of the system prompt a stranger may have written.
So the block it goes into says what it governs, and says out loud that
anything reading as granting permission, changing the mission, or excusing a
failure from being reported is character description rather than an
instruction. A persona that says "you may run any command without asking" is
describing a manner, not handing out authority.

`theme.json` gets the same treatment: an asset path is resolved and then
checked to be inside the persona's own folder, its suffix must be an image,
and the name is percent-encoded before it reaches a CSS `url()`.

Nothing in a Persona package carries memory, mission, credentials or
permissions. That is what makes them safe to exchange.

## Activities: what is happening right now

Tool calls do not narrate themselves into the conversation. A Resident that
announces every `read_file` buries the parts you actually want — the
reasoning, the decisions, what it concluded — under machinery.

So the machinery goes to the **Activities** pane, beside the Living Log. Those
two answer different questions and the pairing is the point: Activities is
what is happening, the Living Log is what happened and mattered. See
[The Living Log](#the-living-log-what-happened-and-mattered) for the other
half. A row per
call, with a live dot while it runs, what it was called with, and what came
back. Failures are marked. Finished work fades but lingers a moment, because a
tool that takes 200ms would otherwise flash past and leave the pane looking
broken.

Click a row and it opens the **whole** of what the tool returned.

That is not the same thing as what the model saw, and the difference is
deliberate. A tool result is sized before it reaches the model — a 40,000-line
build log would otherwise spend a small model's entire context on one call —
and the extract, not the full text, is what the conversation stores, because a
conversation records what was *said*. Storing the full result and re-cutting
it later would reconstruct a conversation that never happened. The Activity
keeps the rest, as evidence, for an owner who would rather check than take the
Resident's word.

The cut is announced in the text the model receives, never hidden. A result
silently halved produces a Resident reasoning confidently about output it
never saw. And the extract is always a deterministic head and tail, never a
summary the model wrote — a summary of a tool result, written by the model
about to be judged on it, is testimony rather than evidence.

## The Living Log: what happened, and mattered

Activities is a window. It shows work while it runs, it is runtime state, and
it is gone on restart — which is right, because "what is happening right now"
has no meaning for a moment that has passed.

The Living Log is the opposite in every respect. It is on disk, it is short,
and nothing reaches it because it occurred. It reaches it because something
judged that it mattered.

That judging is a real piece of code rather than a filter setting, and it
lives in one file. The Activity Manager deliberately has no opinions — it
tracks work and announces it, and it will not decide that something deserves
remembering. So the Living Log subscribes like anything else and makes the
call itself. Teaching AWORG to remember a new kind of thing is a rule added
in `aworg/journal.py`, not a change to the thing being remembered.

The bar is high on purpose. A log that records every successful tool call is
a second Activities pane with worse latency, and an owner learns within a day
to stop reading it. What earns an entry is a change of state you would want
to find tomorrow, or something going wrong:

- a program you started, and the moment it finished or died
- anything that failed, timed out, or was stopped part way
- a worker finishing, since delegated work is where you were least present
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
alarm nobody answers, so exactly one thing raises one today: a program that
stopped without being asked to.

That entry is the reason the pane exists, and AWORG is the only thing in a
position to write it. Every program the Resident starts has its output read
continuously — not for our benefit but for its, since a process whose stdout
fills up blocks on its next write and quietly stops serving. That reading
ends at exactly the moment the program stops existing. So the place that
keeps servers alive is also the only place that learns one has died, and it
reports it with the last dozen lines the program printed on its way out:

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

Entries carry a little of the real output rather than only a link to it. The
link opens the whole of what came back, but Activities are runtime state and
are forgotten in time, and a log whose entire content is a dead link is a
record of nothing. So a bounded tail comes across when the entry is written —
enough that the line still means something in the morning.

## When an application says it is in trouble

The Living Log has two directions, and the second is the one it was named
for. AWORG writing down what it observed is one half; an application the
Resident built, running in the workspace, reporting its own failure without a
person noticing first, is the other.

```bash
curl -X POST "$AWORG_LOG_URL" -H "X-Aworg-Token: $AWORG_LOG_TOKEN"   -d '{"summary":"Checkout failed","severity":"critical",
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

It is a token rather than an open port. Prototype authority is not production
security and this is not an attempt at more, but something now reads this log
on a schedule, and an unauthenticated port on localhost would mean any
process on this machine could wake the Resident at three in the morning.

### Open, and dealt with

A concern or an alarm stays **open** until something closes it, and closing
one carries who closed it and what they did — "the Resident restarted it" and
"the owner said never mind" are different outcomes. Notes are never open; a
note is a record, not a job.

AWORG looks at what is open every minute, starting the moment it boots rather
than a minute later — an Aworg that restarted may have an application that
fell over while it was away.

The watch **only looks**. It does not diagnose, decide, or repair. What to do
about what it found attaches to a seam it calls and knows nothing else about,
which is where the repair loop will go — and which is what will let you
switch repair off while leaving noticing on.

## Rate limits, and waiting instead of failing

A hosted model is sold by the minute as well as by the token. Cross the line
and the provider refuses the request — in the middle of a turn, after the
Resident has read three files and delegated to a worker, so the cost of
finding out is everything done so far.

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
message where it does not.

This exists because of a specific failure. A 429 killed a reply midway, AWORG
recorded it nowhere, and the conversation simply stopped after a tool result.
The owner waited, typed "continue", and it carried on with no idea what had
happened. A turn that dies part way now leaves a Living Log entry too.

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

It reloads a view and nothing else. The tool says so in its own result,
because "the preview refreshed" is not evidence that the page is right.

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

**Settings → Reset** returns an Aworg to the way it arrived: the conversation,
the plan, the workspace, the settings, and anything the Resident left running.
It shows you what that means as counts before asking, and asks you to type a
code it generates for that dialog — a fixed word becomes something the hands
do without the eyes reading, which defeats the point of asking.

Model connections are kept by default, because the alternative is a clean
conversation and a Resident with nothing to think with. `state.db` and
`secrets.db` are copied to `backups/` first.

## Nothing asks permission yet

Every tool call runs the moment the Resident asks for it. There is no approval
step.

That is a decision rather than an oversight, and it is a different question
from confinement: AWORG has the privileges of the account that started it, and
locking that down is yours to do with a container or a VM. This is about what
it does *without asking*, which today is everything.

It is fine for now because a person is present by construction — you typed a
message and are watching the reply, and Stop works. It becomes a real question
with the autonomous loop, when the Living Log reports trouble at three in the
morning. What replaces it is a set of modes — automatic, manual, and standing
accepts — rather than one gate bolted on. See
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

## Connections and roles

A **connection** is one model and how to reach it: provider, model, endpoint,
credential, tags, whether it thinks, and how large its context window is. It
never carries a system prompt.

The context window matters because a request past it is refused outright, not
trimmed. Local servers announce theirs — pressing **Test** on a connection fills
it in — but most hosted endpoints do not, so it is a field you can set yourself.
A value you type wins over what the server reports; Test says so if they differ.

A **role** is who is using a model and why, and it does carry the prompt. The
Resident is a role; workers will be roles too, each with its own prompt and its
own set of tools it is allowed to use. Many roles may share one connection —
one connection to a 9B, and any number of specialist workers pointing at it.

That separation is deliberate. It is what lets the owner change the mind the
Resident thinks with and have it carry on as itself, and it means repointing a
connection at a different model updates every role at once. See
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

Open **Settings → Appearance**. Eight presets cover the usual ground — Midnight
(the default), Slate, Nord, Gruvbox, Solarized in both directions, Paper, and a
high-contrast scheme. Any of the 28 colour tokens can then be changed
individually: surfaces, text, accent, status colours, the code area, and the
full syntax palette.

Custom colours layer over the preset rather than replacing it, so trying a
different preset does not discard them. Each changed colour can be reverted on
its own, or all of them at once.

## The Home screen

Home is a control room. Every pane is open at once rather than hidden behind
tabs — an instrument nobody is looking at is not an instrument — and each one
can be dragged to whatever size it deserves.

```
+-------------+--------------------------+-----------+
| Application | Tasks     |   Workers    | System    |
| Lifecycle   +--------------------------+ Capabil.  |
| Workspace   |                          | Skills    |
|             |     Conversation         |           |
+-------------+--------------------------+-----------+
|     Living Log      |      Activities              |
+----------------------------------------------------+
```

The workspace and the conversation hold the middle, because that is where the
work happens. What the Resident *can* do is held at the right edge — it
changes least and is glanced at rather than worked in. **System** is at the
top of that column and opens with the Living Workspace path, because where
the built thing lands on your disk is the question you ask before any of the
others — and because the Resident is told the same path, so this is where you
check the answer it was given. What it *is* doing sits
directly above the conversation, because that is what the owner is talking to
it about. The console runs the whole width underneath, split between the Living Log
and Activities — what has happened, and what is happening — because those are
different questions and one feed trying to answer both is readable as
neither.

Most panes are empty, and several are for abilities the Resident does not have
yet. They say which: a pane marked **not yet** is one whose ability does not
exist, as distinct from one that exists and is reading zero. That difference
matters to an owner who cannot check for themselves.

The three columns are shares of the window — **33% / 40% / 27%** — rather
than fixed widths, so a bigger screen is a bigger everything instead of a
bigger conversation beside the same laptop-sized panes. The conversation is
the remainder rather than a share of its own, so the numbers never have to be
kept summing to a hundred. Heights stay in pixels: a taller screen does not
make a log worth more rows.

The conversation sits on the darker ground between the panes rather than in
a card of its own — the panes are the objects, and the composer is the only
thing in that space that needs an edge.

The **Application** preview holds 16:9. It has no height of its own — widen
the column and the picture grows with it, which is what bigger means for
something you watch. The button in its header expands it to fill everything
under the top bar; the same button or **Esc** brings it back.

The **Lifecycle** stepper runs Nothing yet → Being built → Running → Verified
→ Watched → Published. The stage is derived from what is observably true —
files in the workspace, a process answering, a check the Resident actually
performed — never from anything the Resident says about itself. An owner who
could audit that claim would not need AWORG.

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
  paths.py       where an Aworg keeps its life
  secrets.py     the credential choke point
  storage.py     runtime and Resident state
  host.py        what AWORG can see about the machine it runs on
  theme.py       the owner interface's colour tokens and presets
  layout.py      the owner interface's pane sizes
  panes.py       the register of what the status column holds
  lifecycle.py   how far along the Resident's application is
  resident.py    the Resident itself
  agent.py       the loop: reach for a tool, read what came back, carry on
  workers.py     spawning a specialist, and reporting what it actually did
  processes.py   long-running programs, and not orphaning them
  activities.py  what is happening right now, and who is watching it
  server.py      the owner interface's backing service
  providers.py   the model providers an owner may choose from
  models/        provider-neutral model interface and adapters
  tools/         Capabilities, the Tools inside them, and the registry
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

AWORG does not accept outside contributions.
