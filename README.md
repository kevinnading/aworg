# AWORG

**Autonomous Workspace Organism** — a persistent AI Resident that lives on your
machine, builds software in its own workspace, and stays on to maintain it.

The concept lives in [docs/](docs/). This file is about running the code.

## Current state

**Milestone 1: the Resident is present, but cannot yet act.**

It can hold a persistent conversation and be connected to any model you choose.
It has no tools, no workspace access, and no ability to run anything — that
arrives in Milestone 2.

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
  workspace/    the Living Workspace (unused until Milestone 2)
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
