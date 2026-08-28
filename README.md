# AWORG

**Autonomous Workspace Organism**

Ive worked on this concept for a long time and now that I have
substantial enterprise AI experience it makes even more sense.

Basically AWORG is an AI based software development system that
acts as an entire software development company.

AWORG handles software development for anyone that can speak or
type with no prior experience.

Install AWORG, run it, tell it what you want to create, it creates
it, it maintains it and it can be embedded in it. Its part of it.

Imagine you use AWORG to build an ERP and as you need more features
and changes you just tell AWORG and it does it for you.

The full concept lives in [docs/](docs/). The rest of this file is about
running the code.

## Current state

**Milestones 1 and 2: the Resident is present and legible, but cannot yet act.**

It holds a persistent conversation and connects to whichever model you choose.
The owner interface is one screen — the application area and Living Workspace
on the left, the conversation down the right. Replies render with syntax
highlighting, and the workspace listing follows along as it changes.

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

Those three zones are separate on disk from the start. Once snapshots exist,
"what may be published" and "what never leaves this machine" must already be
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

## Layout

```
aworg/
  paths.py       where an Aworg keeps its life
  secrets.py     the credential choke point
  storage.py     runtime and Resident state
  resident.py    the Resident itself
  server.py      the owner interface's backing service
  models/        provider-neutral model interface and adapters
  web/           the owner interface
```

The rule that matters: provider-specific detail stays inside `models/`.
Everything above it speaks only AWORG's own vocabulary.
