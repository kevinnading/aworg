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

**Milestones 1 and 2: the Resident is present and legible, but cannot yet act.**

It holds one ongoing conversation — the only one there is, with nothing that
ends it — and connects to whichever model you choose —
hosted, or one running on your own hardware. The owner interface is one screen:
the application area and Living Workspace on the left, the conversation down the
right. Replies render with syntax highlighting, and the workspace listing
follows along as it changes.

It still has no tools, no workspace access, and no ability to run anything.
That arrives in Milestone 3.

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
  workspace/    the Living Workspace (unused until Milestone 3)
  logs/
```

Those zones are separate on disk from the start. Once snapshots exist, "what
may be published" and "what never leaves this machine" must already be
distinguishable, and that is expensive to retrofit.

## Connections and roles

A **connection** is one model and how to reach it: provider, model, endpoint,
credential, tags. It never carries a system prompt.

A **role** is who is using a model and why, and it does carry the prompt. The
Resident is a role; workers will be roles too, each with its own prompt and its
own set of tools it is allowed to use. Many roles may share one connection —
one connection to a 9B, and any number of specialist workers pointing at it.

That separation is deliberate. It is what lets the owner change the mind the
Resident thinks with and have it carry on as itself, and it means repointing a
connection at a different model updates every role at once. See
[docs/06_ARCHITECTURE.md](docs/06_ARCHITECTURE.md).

## Connecting a model

Two adapters cover most of what an owner will want:

- **Anthropic** — leave the endpoint blank
- **OpenAI-compatible** — OpenAI itself, most gateways, and local model servers

For a local model, choose OpenAI-compatible and set the endpoint to something
like `http://localhost:11434/v1`.

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
| Lifecycle   +--------------------------+ Skills    |
| Workspace   |                          | Tools     |
|             |     Conversation         |           |
+-------------+--------------------------+-----------+
|            Living Log, the full width              |
+----------------------------------------------------+
```

The workspace and the conversation hold the middle, because that is where the
work happens. What the Resident *can* do is held at the right edge — it
changes least and is glanced at rather than worked in. What it *is* doing sits
directly above the conversation, because that is what the owner is talking to
it about. The Living Log runs the whole width underneath, the way a console
does, because it is the one thing that reports on all of it.

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
  theme.py       the owner interface's colour tokens and presets
  layout.py      the owner interface's pane sizes
  panes.py       the register of what the status column holds
  lifecycle.py   how far along the Resident's application is
  resident.py    the Resident itself
  server.py      the owner interface's backing service
  models/        provider-neutral model interface and adapters
  web/           the owner interface
```

The rule that matters: provider-specific detail stays inside `models/`.
Everything above it speaks only AWORG's own vocabulary.
