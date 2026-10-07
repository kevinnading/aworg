# AWORG Architecture Decisions

Decisions that are settled, and the reasoning behind them. This is not a
plan — it records choices already made, so that the next person to touch
this code (including a later version of whoever made them) does not have
to re-derive them or accidentally undo them.

## Connections and Prompts

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

**The prompt belongs to whoever is using the model.** The Resident's is its
persona, plus what the owner added to it, plus what AWORG observed; it lives
on the single row in `resident`. A worker's is built by `spawn_worker` for
the one job it was started for, and lives only as long as the worker.

Many of them may share one connection. One connection to a 9B, and fifteen
workers on it, each different by virtue of its own message and its own tools.
Repoint that connection at a different model and everything on it follows,
with no prompt re-entered and no credential duplicated.

What a connection does carry for this is its **tags** — `fast`, `cheap`,
`coding`, `reasoning`, `vision`, `local` — which are what the Resident reads
when it chooses a model for a worker.

### Why not the other two options

**Sub-models with their own prompts, in the manner of Open WebUI**, exist
to give one person many personas. AWORG is built on the opposite premise:
one Resident with one identity, and workers that are assistants for a job
rather than characters. It solves a problem this product does not have.

**Multiple connections to the same model, differing only by prompt**,
duplicates the endpoint, the credential and the model identifier once per
worker. Changing the underlying model then means editing every one of
them, and the connection test becomes N identical checks against one
server.

## Workers

A worker is a whole AI session of its own, short-lived and for one job. The
Resident starts them itself, with `spawn_worker`, as many as it likes and
whenever it likes. There is no roster: an earlier version shipped three fixed
specialists (builder, runner, checker) with owner-set prompts and tool
scopes, and it was removed. The Resident knows the job; a list of
specialists written in advance does not.

A worker is still three things:

    connection      which model it thinks with, chosen by the Resident by tag
    tools           a subset of the Resident's own current tools
    message         the job, and whatever context the Resident sends with it

The tools are an enumeration built from what the Resident holds right now, so
a worker can never be handed something the Resident does not have, and a
Capability the owner switched off is gone from both. The Resident must name
at least one.

**AWORG writes the worker's system prompt, not the Resident.** It is a fixed
base -- *you are my assistant, I started you to do one job, others may be
working in the same workspace, do it, finish it, reply with a summary* --
followed by the descriptions of exactly the tools granted, the machine facts
the Resident is given, and any skills handed over in full. A Resident left to
write that would write the same thing differently every time, and forget the
machine facts -- the first workers started without them spent their jobs
finding out what machine they were on.

### Why workers exist

Not speed, and not specialism. An Aworg's conversation lasts for years and
everything in it is paid for on every message. A worker that reads five
hundred files to fix one bug keeps all five hundred out of it, and hands back
a summary. The Resident's prompt says so in one line: use them for any job
that does not need everything it is holding in context.

A small job is still cheaper done directly, and the Resident is left to judge
that.

### The Resident hears back between turns

A worker's reply does not interrupt. It goes into the inbox
(`aworg/inbox.py`), which delivers everything queued as one message once the
Resident has been idle for a few seconds, so an owner reading the last reply
and typing the next gets there first. The delivery reminds the Resident to
stop the worker once done with it; `message_worker` instead sends it further
down the job with its context intact.

`check_workers` exists for a worker that seems stuck, and says so when the
worker has been running under a minute: a Resident polling its workers is
spending its own context watching them, which is the thing workers exist to
avoid.

### Where the "keep it to five" number does and does not apply

What was measured is that a **2B routes reliably across four or five tools**.
That is a fact about small models with large tool lists. The Resident thinks
with a larger model and its surface can grow well past five as long as each
tool is unambiguous and no two overlap; a worker gets only what it was
granted, which is usually few.

So: add tools where a tool earns its place. Do not refuse a useful tool to
protect a budget that was never about the Resident.

### Workers run in parallel, and nothing locks the workspace

Several run at once. Against hosted models parallelism is wide and real;
against one local GPU it is a handful of slots and contended.

They share one Living Workspace and nothing stops two of them writing the
same file. Each is told that others may be working there. Splitting the work
so that does not happen is the Resident's job, the same as it would be for a
person handing out work.

### What a worker returns

A worker's result carries both what the worker claimed and what AWORG
observed while it worked — exit codes, files actually changed. The
Resident sees both.

This matters more than it looks. A worker reporting success on work that
failed is the exact failure the owner cannot catch for themselves, and it
is not fixed by choosing a better model. It is fixed by the result being
evidence rather than testimony.

## Tools, Capabilities, and the Loop

### Three words, kept apart

    Tool          one callable function a model can ask for
    Capability    an installable folder of related Tools
    Skill         knowing how to do something with the Tools you have

They blur the moment nobody is watching, and the interface has already been
wrong about it once: there was a Tools pane and a Capabilities pane meaning
different things, and Tools never held anything. A Capability is what gets
installed and switched; a Tool is what gets called.

### The loop does not belong to the Resident

The agent loop is a free-standing object (`agent.py`), not a method on
`Resident`. This was got wrong once and the whole tooling layer was rolled
back over it.

A loop that is a method on the Resident is a loop no worker can ever run,
because it is the property of one particular inhabitant rather than something
anything with a model behind it can do. A worker is a connection, a prompt and
a tool scope; it needs exactly what the loop takes and nothing the Resident
owns. So the loop is handed an adapter, a registry, a scope, and a `record`
callback for putting messages somewhere — the Resident's writes to the owner's
conversation, a worker's to a scratch history that is thrown away with it.

If a future change wants to reach `self.store` from inside the loop, that is
the signal it has started belonging to the Resident again.

### MCP is the contract; packaging is ours

Where MCP defines how a tool is described, called and answered, AWORG follows
it. A competing tool-call dialect would buy nothing and would cost every
future external tool an adapter.

What MCP does not define is how a native Python tool is packaged, discovered
or executed, and that half is AWORG's own: a Capability is a folder, a Tool is
a module inside it, and adding one is writing a file rather than registering
anything. Discovery parses each file's declarations without importing it, so a
tool whose dependency is missing is one broken tool rather than an Aworg that
will not start.

Native tools and future external MCP tools enter the same registry and look
the same to the Resident. AWORG keeps its own metadata beside them —
capability membership, enabled state, source — without that leaking into the
MCP boundary.

### Installed Capabilities run as the Aworg

Capabilities come from two places: `aworg/tools/` inside the package, and
`capabilities/` in the Aworg's home. The second is where anything the owner
installs goes, and it loads through the same discovery, the same schema
reading and the same `invoke` as a built-in. The only difference is
mechanical — a folder in the home has no import path, so its modules are
loaded from their files under a synthetic parent package, which is what lets
a capability of several files import between them normally.

An installed Capability runs **in AWORG's process, with everything AWORG
has**. That is the deliberate position, not an unfinished one. A Tool exists
to reach the machine; a Tool that could not would not be a Tool, and a
Resident that can already run shell commands gains no new power from one.
What it does change is *visibility*: a shell command appears in the
conversation, and Python running inside the process need not. So the protection is placed
where it can work — at the moment of installing, in knowing what a capability
is and where it came from — and the interface says plainly which Capabilities
AWORG did not ship.

Two things the home cannot do. It cannot replace a built-in: a folder named
`shell` is refused rather than allowed to stand in front of the real one. And
it cannot declare itself `INTERNAL` or `REQUIRED`; both flags remove a control
from the owner, and an installed folder that could hide from the pane or
remove its own switch would be a capability that installs itself out of sight.
Refusals are shown in the pane rather than swallowed, because a capability
that is silently absent looks exactly like one that was never installed.

Filesystem, Shell, HTTP and the internal capabilities stay in the package.
An Aworg missing them is not a plainer Aworg but a broken one, and a folder
the owner can delete should not be load-bearing.

### Shipped content is a seed, not a second library

Skills, Personas and installed Capabilities live in one place: the Aworg's
home. AWORG ships seven personas and nothing else; `aworg install` copies them
into `personas/` there, and `installed.json` records what it put in. Skills
and capabilities come from the store, and the repository's `personas/`,
`skills/` and `capabilities/` folders are its source -- all eighteen personas
among them, the shipped seven included.

They used to be read from inside the package as well, which made a shipped
skill a different kind of object from one the owner wrote — same format, same
loader, a different home, and invisible in the folder where an owner would go
looking. Now there is one folder per kind and one copy of each thing in it.
Editing a shipped persona edits the persona. Deleting one deletes it, and a
second install leaves it deleted rather than arguing.

"Shipped" survives as provenance rather than location: the installer's record
says AWORG put it there, however much it has been edited since.

### Operating systems are the tools' business

AWORG does not translate between environments and must not start. There is no
compatibility layer in the core, and a tool either handles its platform itself
or reports that it cannot run here — in its own words, which are better than
anything the core could invent.

An earlier attempt had the registry filter tools by `sys.platform`. That is
the same mistake wearing a different hat: a decision about an environment,
made in the core. It was removed. A layer like that is wrong everywhere at
once and grows forever.

### A tool exchange is one indivisible thing

Tool calls and their results are stored as MCP content blocks under real roles
— never under invented ones, and never as private JSON, which is what
previously let a model read its own past as a format to imitate rather than a
conversation to continue.

The consequence that matters: **both wire formats reject a tool result whose
call is missing, and a call whose result never came.** So anything that trims,
interrupts or otherwise ends a round part-way has to keep the pair together.
This has been got wrong twice — once in the context-fitting logic, once in the
stop path — so treat it as the default hazard of any new code that can end a
round early. Every `tool_use` gets a `tool_result`, including "this did not
run".

Because history only grows, a single bad cut is permanent rather than
temporary: the same cut is made on every subsequent turn.

### What the model saw and what actually happened are different records

A tool result is sized before it reaches the model, and **the extract is what
the conversation stores**, because a conversation records what was *said*.
Storing the full result and re-cutting it later would reconstruct a
conversation that never happened.

The whole result is held on the Activity while the Aworg runs. The
Activities pane that used to open it is gone -- the conversation shows every
call as it happens and keeps it -- so today nothing in the interface reaches
past the extract.

Two rules follow. The cut is always announced in the text the model receives,
because a result silently halved produces a Resident reasoning confidently
about output it never saw. And the extract is deterministic, never a summary
the model wrote: a summary of a tool result, produced by the model about to be
judged on it, is testimony rather than evidence.

### Activities track and emit; they decide nothing

An Activity is a runtime object, not a callback. Something creates one, it
moves through a lifecycle, and every transition is emitted to whoever
subscribed. The manager will not start work, will not decide what runs next,
and will not judge that something belongs in the Living Log.

That restraint is the design. A tool call that notified the interface, the
Living Log and its caller directly would have to know about all three; it
knows about none of them, and gains a fourth subscriber without being touched.
Anything that wants to add behaviour to the Activity Manager should become a
subscriber instead — including, if it arrives, the approval step described
below.

The Living Log is the first subscriber to take that seriously rather than
theoretically. It watches the same stream the interface does and decides for
itself what is worth keeping; the manager was not changed to add it, and does
not know it exists.

### A Persona is the system prompt

`PERSONA.md` is the first thing the model reads, as written: there is no
separate AWORG system prompt in front of it. The owner's own additions come
after it, then what AWORG observed about the machine, the skills, the
project and the plan.

There used to be a framing paragraph around the persona saying what it
governed, and that anything in it granting permission was character
description rather than instruction. It went with the old standing prompt,
for the same reason: the model was being told things about its own prompt
instead of being given one. A persona from a stranger is a stranger writing
the system prompt, and the defence is the same as for a capability -- know
where it came from before it is installed. A persona is a page of Markdown,
which makes reading one quick.

The presentation half is filtered, because it can be. An asset path from
`theme.json` is resolved and then checked to be inside the persona's own
directory, its suffix must be a known image type, and the name is
percent-encoded before it reaches a CSS `url()`. Those are closed sets, so a
list is the right tool.

### Changing a Persona cannot lose the Resident

The requirement is that a persona change preserve the conversation, memory,
plan, Living Log, skills, permissions and operational state. The
implementation makes that structural rather than procedural: the active
persona is one nullable column on the Resident's own row, so there is no
sequence of steps that could omit one of them.

The alternative — a change operation that saves and restores the things worth
keeping — would work and would rot. Every feature added afterwards would be
one more thing somebody had to remember to add to the list, and the failure
would be silent and only visible to the owner who lost something.

Nothing chosen is stored as NULL rather than as the default persona's name.
That keeps "I have not chosen" and "I chose this one" as different facts,
which is what lets a factory reset restore the shipped persona without the
storage layer having to know what it is called.

### Noticing and acting are separate objects

`watch.py` reads the Living Log on a schedule and stops. It does not
diagnose, decide, or repair; it holds what is outstanding and calls
`on_trouble` with it.

The seam was drawn before anything used it, so that the repair loop could
not grow inside the watcher -- a little triage, then a little investigation,
then a little fixing -- until the thing that notices and the thing that acts
were one object nobody could reason about separately.

What is on the far side now is the Resident. `on_trouble` puts each report
in the inbox (`aworg/inbox.py`), the same queue worker replies go through,
and the inbox delivers it as a message once the Resident has been idle for a
few seconds. The repair is the Resident's ordinary work, with its ordinary
tools; `resolve_concern` closes the entry and says what was done. A report
that was resolved while it waited is dropped at delivery rather than told
twice.

The split paid for itself as promised. The inspection is testable with no
model attached. And the owner can switch repair off while leaving noticing
on -- **Wakes me** on the Living Log -- which is the difference between an
Aworg that will not fix things and one that cannot see them.

The watcher looks immediately on start rather than after its first interval.
An Aworg that restarted may have an application that fell over while it was
away, and the gap it would be blind across is exactly the gap it exists to
cover.

### The Lifecycle was removed, and why is worth keeping

There was a stepper under the preview — Nothing yet, Being built, Running,
Verified, Watched, Published — and every stage was gated on something AWORG
had observed rather than on anything the Resident said. That part was right
and is worth carrying into whatever replaces it.

What was wrong was the stages themselves. They described one job: build an
application from nothing, on this machine, and start it here. Point an Aworg
at an existing site it maintains but did not create, and every test fails
forever — "running" wanted a process AWORG had spawned, and the web server
was somebody else's. The stepper was not incorrect, it was inapplicable, and
it sat there reading "Being built" over work that had been live for years.

AWORG is more general than the one workflow that stepper knew, so it came
out rather than being patched into vagueness. What replaces it is open.
The shape most likely to survive is a lifecycle defined per project — by the
Resident, at the start of a job — where each stage still names the evidence
that would prove it and AWORG still does the proving. That keeps the
property worth keeping: stages that move **backwards**. Break the
application and the next check fails and the stage drops, with nobody having
to notice and say so. A checklist that only ever advances is a record of
what once happened rather than a description of what is true.

The thing to hold on to is that a stage the Resident can simply assert is
worth nothing, because the owner who needs the stepper is exactly the owner
who cannot audit the claim.

### The Living Log judges; nothing else does

`aworg/journal.py` is the only place in AWORG that holds an opinion about what
deserves remembering, and that concentration is deliberate. Spreading the
decision across the tools would mean every tool carrying a second, quieter
responsibility — and a rule you could only find by reading all of them.

Two things follow from the split.

Failure is judged centrally, from the Activity stream, so a tool does not
need to know the Living Log exists in order to be reported when it breaks.
The few tools that write entries directly are the ones whose *effect outlives
the call* — a plan being made, a task ending — which the Activity stream
cannot see, because from outside they are ordinary successful tool calls.

And the durability is the point. Activities are runtime state, capped and
gone on restart; the journal is a table. An owner asking what happened
overnight is the case this exists for, and runtime state answers that
question with silence. That is also why an entry copies a bounded tail of the
real output rather than only linking to the Activity holding it: the link
goes dead, and an entry that is only a dead link records nothing.

Three levels rather than a `bad` flag, because the autonomous repair loop
will have to tell "something failed and was handled" from "something is wrong
now" — a loop that cannot separate those either wakes for everything or
sleeps through the outage. Today exactly one event raises `alarm`: a program
that stopped without being asked to.

That event is also the one thing in AWORG no model and no tool can report.
Every started program has its output drained continuously, because a process
whose stdout fills blocks on its next write and silently stops serving. That
drain ends precisely when the program stops existing, which makes it the only
observer of a death nobody asked for. Distinguishing it from a deliberate
stop requires the intent to be recorded *before* the process is signalled;
set afterwards, it races with the death it exists to explain.

### Skills cannot be relied on at this size, and that is measured

AWORG implements the Agent Skills convention properly: descriptions in the
prompt, bodies fetched with read_skill. Whether a model *uses* it is a
different question, and on everything that fits 8GB the answer is no.

Measured on identical prompts, five runs each, with a skill whose description
reads "use before creating any new file, of any kind":

    model              reads a skill   follows it   routes correctly
    qwen3.5-9b              0/5            0/5           3/5
    qwen3.5-9b thinking     0/4            0/4           1/4
    granite-4-micro         2/5            0/5           1/5
    qwen3.5-2b              0/5            0/5           3/5

Four explanations were tested and eliminated. The description was rewritten
three ways including one stuffed with the surface words of the request --
one read in eighteen runs. The instruction was moved into the standing
prompt where "plan first" lives -- no change. Thinking was turned on, on the
theory that consulting a reference needs a pause to wonder whether one
exists -- it did not help and made routing worse. And a larger model was
tried: the 9B scores identically to the 2B at three times the VRAM.

A fifth explanation was tested and *partly* held, which qualifies all of the
above. Every one of those runs asked for one small script -- the least
favourable case, since a model with no felt difficulty has nothing to prompt
it to check anything. Asked instead for a four-page site with a server,
granite-4-tiny read the skill in one run of three and planned in that same
run.

But it read it *after* writing five files. A procedure consulted once the
work is done has not been followed; it has been noticed, and the conventions
it describes were already broken. So the qualified finding is: these models
never consult a skill for small work, and consult one late for large work,
and neither is something behaviour can be built on.

**Nothing followed a skill it had read.** Granite read one twice and ignored
it both times, which is worse than never looking: a model that consults a
procedure and then does its own thing cannot be caught at it.

The conclusion is about models rather than about AWORG. Consulting a
reference before acting on a familiar request is not a tool-use skill; it is
a disposition to suspect that this machine differs from the training data,
and it is absent at this scale. Do not work around it -- an accommodation
was built once, as an `always` field carrying skill bodies in the prompt, and
removed for turning a measurement about one model into a permanent feature of
a file format.

What this means in practice: skills are built and correct, they matter on a
capable model, and on a local floor model they are inert. That is the same
shape as tool support varying by provider, and it is reported the same way
rather than hidden.

### On a capable model they are read every time, and help where they carry facts

Measured 2026-10-07 on gpt-6-luna, the six store skills, one job each, run
once with the skill installed and once without, from a reset Aworg:

    skill          read it   difference it made
    site-check     yes       10 of 10 planted defects, measured in a browser,
                             against 7 of 10 guessed from the source without
    mobile-first   yes       16px inputs (12px without), 0 low-contrast
                             elements (11 without), safe-area padding
    skill-writer   yes       description gained its when-to-use half, the
                             generic checklist went, 43 lines against 58
    design-taste   yes       took the skill's heading face; ignored its type
                             scale, still 17 sizes down to 9px
    ask-first      yes       built anyway, under the skill's own "under ten
                             minutes, just build it" clause; said its defaults
                             (the clause has since been removed)
    bug-hunt       yes       none: the planted bug was easy enough that both
                             runs found and fixed it identically

Six reads in six, against one in eighteen on the 9B. The pattern matches
what the skills README predicts: a skill wins where it carries numbers and
checks the model would not produce alone, and adds nothing where the model
already does the job.

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
machine taken at boot describes the first day of a month-long life. They are
kept apart from what the owner adds to the Persona rather than written into
it: that text is the owner's to write, the facts are AWORG's to observe, and
mixing the two would leave the owner maintaining a description of their own
machine.

### Tool calls are not gated, and that is on purpose for now

There is no approval step between the Resident asking for a tool and the tool
running. Every call executes immediately. **AWORG has full control.**

This is a decision rather than an omission, and it is worth separating from
the section above. Confinement is about what AWORG *could* do, and it is the
owner's, settled with a container or a VM. This is about what AWORG does
*without asking*, which is a different axis and is AWORG's own question.

When the owner typed the message, a person is present by construction: they
are watching the reply arrive, and Stop works. When an application's report
wakes the Resident at three in the morning, nobody is. That case exists now,
and the only control over it is the owner's **Wakes me** switch -- all or
nothing.

What may replace that is a set of modes — automatic, manual, and standing
accepts for particular things — rather than a single gate. That is a design
worth doing properly and it is not built.

If it arrives, it should not need new machinery. The Activity lifecycle
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
observed, never from what a model reported. The preview shows a page because
something is actually serving one; the Living Log's entries come from the
Activity stream rather than from a Resident's summary of its own work; a
worker's result carries what AWORG watched it do beside what it claimed.

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
