# AWORG Milestone 1

## Goal

Establish the smallest version of AWORG that is genuinely alive:

> **An owner can talk to a persistent Resident through a browser, and
> can choose which model that Resident thinks with.**

Nothing is built by the Resident yet. It cannot touch files, run
commands, or create software. Milestone 1 exists to make the
relationship real — a Resident that is present, remembers, and can be
reconnected to a different mind without losing itself.

## The Experience

The owner starts AWORG and opens the owner interface in a browser.

There are two places to be: **Chat** and **Settings**.

### Chat

The owner writes to the Resident and the Resident answers, its reply
appearing progressively rather than arriving all at once. The
conversation is continuous — closing the browser, or shutting AWORG down
entirely and starting it again later, returns the owner to the same
ongoing conversation rather than a blank slate.

The owner can always see which model the Resident is currently thinking
with, and can deliberately begin a fresh conversation when the current
one has run its course.

When something goes wrong — a model that cannot be reached, a credential
that is no longer valid — the Resident says so plainly instead of
failing silently.

Throughout, the interface speaks of the **Resident**. Not an assistant,
not a bot. The language should establish from the first screen that this
is an inhabitant, not a feature.

### Settings

Settings is where the owner decides what the Resident is connected to.

**The Primary Resident.** The owner chooses which model connection the
Resident currently uses, and can give the Resident standing instructions
about who it is and how it should work.

**The Model Pool.** The owner can define any number of additional model
connections beyond the primary one. Each connection is given a
recognizable name, identifies the provider and the specific model, and
carries whatever credential and address are needed to reach it —
including models served from local machines or third-party endpoints,
not only the major hosted providers. Connections can be switched on and
off without being deleted.

Each connection can also be tagged with what it is good for:

- reasoning
- coding
- fast
- cheap
- vision
- local

Milestone 1 does not use these tags for anything. Nothing routes work
automatically and no workers exist yet to delegate to. The tags are
established now because a later Resident that dispatches bounded work to
temporary workers will need exactly this vocabulary, and discovering
that after the fact would mean rebuilding how the owner thinks about
models.

### Model Agnosticism

AWORG is not the interface to one company's model. The owner supplies
the minds; AWORG supplies the residency. Supporting custom and local
endpoints from the very first milestone keeps that commitment honest
rather than aspirational, and prevents the Resident's identity from
becoming entangled with any single provider.

## What Persists

Everything the owner has established survives a restart: the
conversation, the configured connections, which one is primary, and the
Resident's standing instructions.

Credentials are treated as private from the beginning. They are the
owner's property, not incidental configuration, and they should never
surface in ordinary operational output.

## Milestone 1 Is Complete When

An owner can install AWORG, open it in a browser, connect it to two
different models, choose one of them as the Resident, and hold a real
conversation. They can close everything, come back later, and find the
conversation waiting. They can then point the Resident at the second
model and continue the same conversation — the Resident's memory and
identity intact, only the mind behind it changed.

That last moment is the point of the milestone. It demonstrates that the
Resident is a persistent inhabitant of the machine rather than a thin
wrapper around whichever model happens to be configured.

## What Comes Next

Milestone 2 makes the relationship workable: one screen where the
Resident's replies can be read comfortably, where the Living Workspace
stays in view, and where a place waits for whatever eventually gets
built.

The Resident gains no new abilities there. It gains them in Milestone 3,
which gives it the ability to act inside its workspace rather than only
discuss it.
