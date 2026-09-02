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

## The status column

The left side of Home is a control room. Every pane is open at once rather
than hidden behind tabs — an instrument nobody is looking at is not an
instrument — and the column scrolls:

```
Application       the software the Resident is responsible for
Lifecycle         how far along it is
Living Workspace  everything the Resident has made
Workers           temporary sub-agents put to work
Tasks             what the Resident is doing
Living Log        what the running application reports about itself
Tools             what the Resident can directly do
Skills            procedures it knows how to carry out
Capabilities      the sum of what this Aworg is able to do
```

Most of those are empty, and several are for abilities the Resident does not
have yet. They say which: a pane marked **not yet** is one whose ability does
not exist, as distinct from one that exists and is reading zero. That
difference matters to an owner who cannot check for themselves.

The **Lifecycle** stepper runs Nothing yet → Being built → Running → Verified
→ Watched → Published. The stage is derived from what is observably true —
files in the workspace, a process answering, a check the Resident actually
performed — never from anything the Resident says about itself. An owner who
could audit that claim would not need AWORG. Stages beyond what the current
milestone can produce evidence for are drawn as out of reach rather than
merely unfinished.

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
