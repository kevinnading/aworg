# AWORG Architecture Decisions

Decisions that are settled, and the reasoning behind them. This is not a
plan — it records choices already made, so that the next person to touch
this code (including a later version of whoever made them) does not have
to re-derive them or accidentally undo them.

## Connections, Roles, and Prompts

Three concepts, deliberately separate.

**A connection is how to reach a model.** One connection per model:
provider, model identifier, endpoint, credential, capability tags, and
runtime configuration that belongs to the model itself — temperature,
whether reasoning is enabled, context limits.

**A connection never carries a system prompt.**

That rule is the whole point. The Resident's identity already lives apart
from the model behind it, so the owner can change the mind the Resident
thinks with and have it carry on as itself. Put a prompt on a connection
and that dies quietly: switching from a local model to a hosted one would
change who the Resident *is*, because the identity arrived with the
endpoint.

**A role is who is using a model, and why.** A role carries the system
prompt, points at a connection, and — for workers — carries the set of
tools it is allowed to use.

Many roles may share one connection. One connection to a 9B, and fifteen
workers pointing at it, each a specialist by virtue of its own prompt and
its own tool scope. Repoint that connection at a different model and every
role follows, with no prompt re-entered and no credential duplicated.

The Resident is a role. Today it is a single row in `resident`, which is
that table with one seat in it; the shape generalises when workers arrive.

### Why not the other two options

**Sub-models with their own prompts, in the manner of Open WebUI**, exist
to give one person many personas. AWORG is built on the opposite premise:
one Resident with one identity, and workers that are tools rather than
characters. It solves a problem this product does not have.

**Multiple connections to the same model, differing only by prompt**,
duplicates the endpoint, the credential and the model identifier once per
worker. Changing the underlying model then means editing every one of
them, and the connection test becomes N identical checks against one
server.

## Workers

Workers are temporary. They are spawned for one bounded job, they do not
remember anything once it is finished, and they are disposed. Keeping a
worker alive across a multi-part job is a later version, not this one.

A worker is three things, not two:

    connection      which model it thinks with
    system prompt   how it works
    tool scope      what it is allowed to do

The third is the one that is easy to miss and does the most work. A
test-runner that cannot write files cannot damage the workspace however
badly it misreads a job — it is not trusted to avoid writing, it is simply
not handed the means. Note that this is a limit the Resident places on a
worker it spawned, not a limit AWORG places on the Resident; see *Authority
Is The Account's* below. It is also what makes small models usable as
specialists — three tools and a narrow prompt are far more reliable than
twelve tools and a general one.

### Delegation is one tool, not one per worker

The Resident delegates through a single tool whose `worker` parameter is
an enumeration of the configured workers:

    delegate(worker, task) -> job id

Not one tool per worker. Tool-selection accuracy falls away as the tool
surface grows; measured on the models this is developed against, routing
is reliable at around five tools and not at fifteen. One tool with an
enumeration keeps the surface flat no matter how many specialists the
owner defines, and turns the Resident's job into routing — picking from a
list — which even very small models do well.

The consequence is that **a worker's description is load-bearing**. It is
the only thing the Resident routes on. A vague description is a misrouted
job, and the owner experiences that as the wrong specialist doing their
work without ever seeing why. Descriptions deserve the same care in the
interface as prompts.

### Workers run in parallel

Several may run at once. The interface is concurrent even where execution
is not: against hosted models parallelism is wide and real, against one
local GPU it is a handful of slots and contended, so the cap belongs to
the connection rather than being global.

### Concurrent writes are handled by locking in the tools

Parallel workers share one Living Workspace, so two of them can edit the
same file. Every write already passes through the tool layer, which makes
that the one place a lock is unavoidable rather than merely conventional.
It also covers the case a per-worker scheme would miss: the Resident and a
worker writing the same file, not only two workers.

### What a worker returns

A worker's result carries both what the worker claimed and what AWORG
observed while it worked — exit codes, files actually changed. The
Resident sees both.

This matters more than it looks. A worker reporting success on work that
failed is the exact failure the owner cannot catch for themselves, and it
is not fixed by choosing a better model. It is fixed by the result being
evidence rather than testimony.

## Authority Is The Account's, Not AWORG's

Earlier drafts of this project described a boundary around the Living
Workspace, structurally enforced, with the Resident held inside it. That is
not what AWORG is.

A Resident that builds an application also installs what the application
needs: runtimes, services, system packages, sometimes daemons. Most of that
lives outside any workspace by definition. A boundary drawn around the
workspace would either be a lie the moment the Resident installed anything,
or a cage that stopped it doing the job.

The Living Workspace is a *suggestion*, then, not a fence: the place the
Resident builds an application by convention, so that "the thing that was
built" stays identifiable when snapshots arrive. It says nothing about where
the Resident may work. Helping run the machine — installing services,
changing configuration, tidying what is already there — is part of the job,
and none of it happens in `workspace/`.

So there is no boundary here. **AWORG runs with exactly the privileges of
the account that started it.** Run it as yourself and it is you; run it as
root and it is root; run it inside bubblewrap, a container, or a VM and it
is whatever that allows. Confinement is the owner's decision, made when they
launch it, with tools far better at it than anything this project would
write.

What AWORG owes the owner instead is **honesty about what it has**. The host
is observed at every start -- operating system, package manager, whether the
process is elevated, what is on PATH -- and those facts are shown in the
Capabilities pane and sent to the Resident with every message. An owner about
to ask for postgres can see beforehand whether this Aworg could install it.
A Resident that knows it is on Windows does not propose `apt install`.

The facts are gathered at start rather than once at install, because a
machine surveyed at install time is wrong the first time its owner installs
anything — and re-gathered once they are more than a few hours old, because
an Aworg is started once and then left running for weeks. A picture of the
machine taken at boot describes the first day of a month-long life. They are kept beside the owner's standing instructions rather than
written into them: the instructions are the owner's to write, the facts are
AWORG's to observe, and mixing the two would leave the owner maintaining a
description of their own machine.

### Tool calls are not gated, and that is on purpose for now

There is no approval step between the Resident asking for a tool and the tool
running. Every call executes immediately. **AWORG has full control.**

This is a decision rather than an omission, and it is worth separating from
the section above. Confinement is about what AWORG *could* do, and it is the
owner's, settled with a container or a VM. This is about what AWORG does
*without asking*, which is a different axis and is AWORG's own question.

Today the answer is easy because a person is present by construction: the
owner typed a message and is watching the reply arrive, and Stop works. The
question only becomes real with the autonomous loop, when the Living Log
reports trouble at three in the morning and the Resident repairs it with
nobody there.

What replaces this is a set of modes — automatic, manual, and standing
accepts for particular things — rather than a single gate. That is a design
worth doing properly and it is not this milestone's.

When it arrives, it should not need new machinery. The Activity lifecycle
already has `waiting` and `timed_out`, and neither is ever entered:

    call needs a person  ->  Activity enters `waiting`, and emits
                         ->  subscribers decide what that means: the pane
                             offers Approve or Refuse, a notifier reaches
                             the owner wherever they are
                         ->  they answer, or nobody does and it times out

Which is the Activity Manager's own principle applied to permission: it
tracks and emits, and what a `waiting` Activity *means* is the subscriber's
business. Building the gate as another subscriber rather than as a branch
inside the tool layer is what keeps the tool layer from slowly becoming
where all policy lives.

Two things will need deciding and neither is decided here. What marks a call
as needing a person — a shell tool cannot reliably read intent out of a
command string, so capability-level rules may hold where per-call judgement
will not. And what happens when nobody answers, given that waiting forever is
safe and defeats the entire point of an unattended repair.

### The consequence for snapshots

The white paper separates `workspace/` -- what may be published -- from
everything that never leaves the machine. If the Resident installs services
system-wide, a workspace snapshot will not reproduce the application:
whoever loads it gets the code and none of its dependencies.

That is not a reason to confine anything. It means the snapshot story will
eventually need the Resident to record what it installed outside the
workspace, as a manifest rather than a restriction. Cheap to record as it
happens, expensive to reconstruct afterwards.

## Verification Is A Property Of The System

Anything AWORG shows the owner about progress is derived from what it
observed, never from what a model reported. The application's lifecycle
stage advances on evidence — files present, a process answering, a check
that actually ran — and stages beyond what the current milestone can
evidence are shown as out of reach rather than merely unfinished.

The reason is the product's own premise. An owner who could audit the
Resident's claims would not need AWORG. A well-prompted Resident that
verifies is good; a system in which "verified" cannot be claimed without
evidence is better, and it is what the autonomous repair loop will have to
stand on.

## Developed Against The Worst Case

The models this is built against are deliberately modest — a 9B for the
Resident and a 2B for workers, both quantised onto a single 8GB card.
They are not a recommendation. They are a floor: if the loop holds
together with these, better models come free.

What that implies, and what should not be quietly abandoned when something
stronger is plugged in:

- keep the tool surface small and each tool unambiguous;
- keep system prompts short — measured, longer ones scored *worse*;
- validate tool arguments before executing rather than trusting them;
- assume a small context, so conversation history is managed early.
