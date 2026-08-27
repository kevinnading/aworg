# AWORG MVP

## Objective

Prove the core AWORG thesis with the smallest credible product.

The MVP is **not** the marketplace, the full snapshot ecosystem, an
enterprise permission system, a polished cross-platform installer, or a
complete autonomous agent platform.

The MVP must demonstrate that a Resident can live on a machine, create
software, keep developing it, observe it, and maintain it.

## MVP Success Statement

A user should be able to:

1.  install and start AWORG;
2.  open the owner interface;
3.  configure a model;
4.  tell the Primary Resident what application they want;
5.  watch the Resident create and run the application in its workspace;
6.  see the application in a live preview;
7.  request changes conversationally;
8.  have the application report structured events to the Living Log;
9.  have AWORG periodically inspect the Living Log;
10. observe the Resident autonomously diagnose and repair an induced
    application failure;
11. continue using and modifying the repaired application without
    touching source code.

If that loop works convincingly, the MVP has proven AWORG.

## What the MVP Must Provide

### The Aworg Itself

The owner can install AWORG, start it, and reach it through a browser.
Its configuration persists. It has a clearly designated Living Workspace
that belongs to the Resident, and it can start and stop the software
running inside that workspace.

### The Resident

One authoritative Primary Resident, with a persistent conversation and
project understanding that survives restarts, connected to a model the
owner chose.

Within its workspace it must be able to genuinely act: read and change
what is there, run programs and commands, install what an application
needs to run, and start and stop that application. It must be able to
inspect its own work rather than assume it succeeded.

If temporary workers prove inexpensive to support, the Resident may
delegate bounded tasks to them. This is desirable but not required.

### Application Preview

For web applications, the owner sees the running application live in the
owner interface, in a prominent 16:9 view, with the ability to refresh
it, open it fully, and expand it.

The preview should reflect the application's current state after the
Resident changes it.

Fullscreen interactive visual editing is **post-MVP** unless it proves
exceptionally inexpensive.

### The Living Log

Applications must be able to report meaningful operational events to the
Resident: when something failed, where it happened, how serious it is,
and whatever surrounding detail would help diagnose it.

The vocabulary of severities and categories should stay deliberately
small at first. What matters is that the channel exists, that events are
structured enough to be reasoned about rather than merely read, and that
AWORG periodically examines unresolved ones.

This is the mechanism that lets software tell its Resident something is
wrong without a human noticing first.

### The Autonomous Repair Loop

This is the heart of the MVP. For an eligible error, the Resident must:

1.  detect the Living Log event;
2.  wake and take up the problem;
3.  investigate the application's code, state, and behavior;
4.  form a repair plan;
5.  make the change;
6.  test or otherwise check the result;
7.  restart the application if needed;
8.  verify the error no longer occurs;
9.  record what it did and why.

The first implementation may be conservative and narrow. It does not
need to solve arbitrary failures. It needs to genuinely close this loop
without a human initiating it.

### The Dashboard

At minimum the owner should be able to see: what the Resident is and
what model it is using, what it is currently doing, the running
application and whether it is healthy, the live preview, and recent
Living Log activity. Basic machine health may be included if it is
cheap to surface.

### History and Reversibility

Meaningful changes the Resident makes should be recorded as a history
that can be reviewed and undone, each entry carrying a human-readable
explanation of what changed.

Branching, publishing, visual comparison, and snapshot export are not
MVP requirements.

### Skills and Tools

A simple internal notion of skills and tools, with a small default set
shipped. No public registry or ecosystem for the MVP.

## Explicitly Deferred

The following are intentionally not required:

-   public ecosystem;
-   marketplace;
-   paid packages;
-   publishing interface;
-   snapshot distribution;
-   snapshot sanitization;
-   complex licensing;
-   elaborate permission system;
-   multi-user accounts;
-   enterprise controls;
-   billing;
-   perfect cross-platform parity;
-   native installers;
-   visual DOM editing;
-   drag-select editing;
-   advanced memory architecture;
-   complex model routing;
-   sophisticated cost optimization;
-   extensive analytics;
-   full backup/restore system;
-   distributed orchestration;
-   production-grade package signing;
-   complete security sandbox.

## Prototype Authority Is Not Production Security

Do not confuse the two.

The MVP may grant the Resident broad authority inside a clearly
designated development workspace in order to prove the concept. A
production release will require substantially stronger isolation,
secrets handling, package verification, prompt-injection boundaries, and
permission enforcement.

Deciding this deliberately now prevents a prototype shortcut from
quietly becoming the shipped security model.

## Initial Target

Prioritize **web applications**.

Nothing in the MVP should assume that generated software is always
web-based. Web-first is a focusing decision, not a permanent constraint
on what a Resident can build.

## MVP Demo Scenario

A strong demo might be:

1.  Owner installs AWORG.
2.  Owner says: "Build me a simple customer database for my landscaping
    company."
3.  Resident creates a web application with customer records.
4.  Application appears in the preview.
5.  Owner says: "Add phone search and customer notes."
6.  Resident updates the app.
7.  A deliberately introduced bug causes part of the app to fail.
8.  The application reports the error to the Living Log.
9.  Resident notices the event without owner intervention.
10. Resident diagnoses the error.
11. Resident fixes it.
12. Resident tests and restarts the app.
13. The Living Log shows a successful autonomous repair.

That demonstration communicates the AWORG concept more effectively than
a large feature checklist.
