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

It now has hands: five tools across three Capabilities, so it can read, write
and search files, run commands, and make HTTP requests. What it is doing shows
up in the **Activities** pane as it happens.

What it does not have yet is workers to delegate to, the Living Log, or the
autonomous repair loop — the parts that would let it work with nobody
watching.

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

Three Capabilities ship, and they are prepackaged rather than special — they
load by the same path anything downloaded later will:

```
Filesystem   read_file  write_file  search_files
Shell        execute_command
HTTP         http_request
```

Five tools, and the number is deliberate. Tool-selection accuracy falls away
as the surface grows: on the models this is developed against — a 9B and a 2B
— routing is reliable at around five and not at fifteen. Capability is the
unit of enablement partly so that stays true as more arrive. `search_files`
is one tool rather than three because listing a directory, matching filenames
and searching contents are one question asked in three moods.

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

## Activities: what is happening right now

Tool calls do not narrate themselves into the conversation. A Resident that
announces every `read_file` buries the parts you actually want — the
reasoning, the decisions, what it concluded — under machinery.

So the machinery goes to the **Activities** pane, beside the Living Log. Those
two answer different questions and the pairing is the point: Activities is
what is happening, the Living Log is what happened and mattered. A row per
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
| Application | Tasks     |   Workers    | Capabil.  |
| Lifecycle   +--------------------------+           |
| Workspace   |                          | Skills    |
|             |     Conversation         |           |
+-------------+--------------------------+-----------+
|     Living Log      |      Activities              |
+----------------------------------------------------+
```

The workspace and the conversation hold the middle, because that is where the
work happens. What the Resident *can* do is held at the right edge — it
changes least and is glanced at rather than worked in. What it *is* doing sits
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
