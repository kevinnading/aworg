# AWORG: Autonomous Workspace Organism

## Abstract

AWORG proposes a different relationship between artificial intelligence
and software.

Most AI development systems treat AI as an external assistant: a person
requests software, the AI writes or edits code, and the resulting
application remains a conventional software artifact. AWORG instead
treats the AI as a **persistent resident of a compute environment**. The
Resident creates software inside that environment, operates it, observes
it, maintains it, and continues evolving it over time.

The user does not need to become a programmer. The user expresses
intent; the Resident performs software development.

The long-term vision extends beyond generation. AWORG introduces the
idea of **Living Software**: applications that retain a resident
developer/operator, report their own operational state through a
structured Living Log, can be evolved conversationally, and can
eventually be snapshotted, forked, inherited, published, and continued
by other owners and Residents.

## 1. The Problem

AI has dramatically reduced the effort required to generate code, but
much of the surrounding software lifecycle remains conventional:

-   users still think in terms of projects and codebases;
-   AI builders are often external to the finished application;
-   maintenance begins after generation;
-   debugging is generally initiated by a human;
-   generated applications do not inherently retain the AI that created
    them;
-   sharing usually means sharing source code or a deployed application;
-   extending another person's application still assumes
    software-development knowledge.

The deeper opportunity is not merely faster code generation. It is
changing the unit of software development from **source code operated by
programmers** to **persistent software environments operated through
intent**.

## 2. The AWORG Concept

An **Aworg** is an **Autonomous Workspace Organism**: a persistent AI
system that inhabits a computer, VM, server, container, or virtual host
and has a designated workspace in which it can create and maintain
software.

The owner interacts with the Resident through a browser-based control
interface. The Resident can be connected to a model of the owner's
choice and is intended to remain model-agnostic.

At a conceptual level:

``` text
OWNER
  |
  v
AWORG OWNER INTERFACE
  |
  v
PRIMARY RESIDENT
  |
  +--> tools, capabilities, and skills
  +--> temporary sub-agents
  +--> memory / tasks / automations
  +--> Living Log
  |
  v
LIVING WORKSPACE
  |
  +--> website
  +--> web application
  +--> API/service
  +--> native executable
  +--> CLI
  +--> other software
```

The Resident is not simply a chatbot embedded into an application. It is
the persistent developer and operator responsible for the workspace.

## 3. Stable Runtime, Evolving Workspace

A critical architectural boundary is that **AWORG itself does not need
to rewrite itself**.

The AWORG runtime is distributed and updated conventionally by its
maintainers.

The Resident receives broad authority inside a designated **Living
Workspace**.

``` text
AWORG Runtime       -> maintained by AWORG project
Living Workspace    -> controlled/evolved by Resident
Private State       -> credentials, owner data, memories
```

This separation improves reliability, update compatibility, licensing
clarity, and security.

## 4. Model Agnosticism

AWORG should not be synonymous with any particular frontier model.

The owner configures a **Primary Resident model** and may configure a
**Model Pool** containing additional providers, models, or compatible
endpoints.

Connections may include:

-   hosted frontier models;
-   lower-cost/fast models;
-   coding-specialized models;
-   vision-capable models;
-   reasoning models;
-   models running locally on the owner's own hardware;
-   models reached through third-party or self-hosted endpoints.

Models can be tagged with capabilities such as `reasoning`, `coding`,
`fast`, `cheap`, `vision`, or `local`.

The Primary Resident remains authoritative while delegating bounded
tasks to temporary sub-agents using suitable models from the pool.

## 5. One Resident, Many Workers

One Aworg should have **one authoritative Primary Resident**.

The Resident owns:

-   the relationship with the owner;
-   high-level understanding of the workspace;
-   persistent project memory;
-   priorities and decisions;
-   interpretation of the Living Log;
-   delegation;
-   integration of worker results.

Sub-agents are temporary workers, not peer identities. The Resident may
spawn them for research, coding, testing, diagnosis, review, or other
bounded work.

``` text
                  OWNER
                    |
             PRIMARY RESIDENT
                    |
       +------------+------------+
       |            |            |
    Worker       Worker       Worker
       |            |            |
       +------------+------------+
                    |
                 Results
                    |
             PRIMARY RESIDENT
                    |
              LIVING WORKSPACE
```

This provides continuity without sacrificing parallelism or model
specialization.

## 6. The Living Log

The **Living Log** is intended to become a signature AWORG capability.

Traditional application logs are primarily written for developers. The
Living Log is a structured operational communication channel between the
software and its Resident.

Applications can emit structured events such as:

-   informational events;
-   warnings;
-   errors;
-   performance events;
-   security events;
-   user feedback;
-   explicit requests for AI attention.

The Resident periodically inspects the Living Log. When it detects a
meaningful problem, it can investigate the workspace, reproduce the
issue, modify the application, test the change, restart/redeploy as
appropriate, and verify that the problem is resolved.

The desired loop is:

``` text
Application experiences problem
        |
        v
Living Log records event
        |
        v
Resident detects event
        |
        v
Resident investigates
        |
        v
Resident modifies application
        |
        v
Tests / restart / verification
        |
        v
Incident resolved and recorded
```

This changes the Resident from an on-demand coding assistant into an
ongoing software maintainer.

## 7. Owner Interface

The owner interface is browser-based even when the software produced by
the Resident is not.

The long-term dashboard is envisioned as a control room for the living
system, including:

-   live application preview;
-   Resident status;
-   Resident chat;
-   tasks;
-   automations;
-   upcoming events;
-   running sub-agents;
-   Living Log;
-   system/application health;
-   skills;
-   tools;
-   model configuration;
-   history/evolution;
-   snapshots and publishing.

For web applications, the dashboard should provide a 16:9 live preview
that can expand into a fullscreen application view.

A future **interactive edit mode** can place a translucent Resident chat
overlay over the fullscreen application. The owner can select an element
or region and request changes conversationally while the Resident
receives the selected application context.

Chat should ultimately be an interface layer over the entire system
rather than merely a separate page.

## 8. Resident API

Software created by an Aworg may optionally use the Resident itself as
infrastructure.

For example, a public website could contain an AI chat experience that
calls the Resident API while operating under a tightly restricted
user-facing context.

This creates two fundamentally different interfaces:

**Owner Interface**\
High-authority relationship with the Resident for development and
operation.

**Application Interface**\
Restricted API/context through which application users may access
selected AI capabilities.

Security boundaries must prevent public application interactions from
inheriting owner/developer authority.

Not every generated application must depend on AWORG. A Resident may
create a completely standalone native executable that continues
functioning without the AWORG runtime. AWORG remains its
developer/maintainer rather than necessarily becoming its runtime
dependency.

## 9. Skills, Tools, Automations, and Capabilities

AWORG should distinguish between reusable capability types.

### Tools

Things the Resident can directly use, such as filesystem access, command
execution, browser automation, version control, databases, network
access, external APIs, and image generation.

### Skills

Reusable procedures or learned capabilities describing how to accomplish
tasks effectively.

### Automations

Reusable recurring or triggered behaviors, such as health scans,
backups, reports, dependency checks, or application-specific workflows.

### Packages / Packs

Future bundles may combine skills, tools, automations, prompts,
templates, or domain knowledge.

The initial installation may include a curated set of common defaults.
The long-term ecosystem allows users and creators to discover and
install additional capabilities.

## 10. Living Software Ecosystem

The ecosystem is a primary part of the long-term product thesis.

Users should eventually be able to publish and distribute:

-   Living App snapshots;
-   skills;
-   tools;
-   automations;
-   capability packs;
-   templates;
-   potentially other reusable artifacts.

A domain expert who cannot program could teach their Resident to build a
highly specialized workflow, package the resulting capability, and
contribute it to others.

This creates an ecosystem where software capability can be created
through domain expertise and natural language rather than only
traditional programming.

## 11. Snapshots and Software Lineage

A future AWORG snapshot represents a portable state of a Living
Workspace at a meaningful point in its evolution.

A snapshot may include:

-   application source;
-   schema/migrations;
-   assets;
-   tests;
-   generalized knowledge;
-   skills;
-   application manifest;
-   architectural information;
-   dependency information;
-   compatibility metadata;
-   lineage metadata.

It must exclude or sanitize private owner state such as secrets,
credentials, personal memories, private files, and customer data unless
intentionally included.

A second person can obtain a snapshot, restore it into their own Aworg
environment, connect their own Resident/model configuration, and
continue development from that point.

This turns software distribution into:

``` text
Create -> evolve -> snapshot -> publish -> fork -> continue evolving
```

rather than:

``` text
Write -> release -> install
```

## 12. Evolution, Transport, and Discovery

Living Software needs a recorded evolutionary history. Every meaningful
change a Resident makes should be preserved with a readable explanation
of what changed and why, so that history can be reviewed, compared, and
reversed.

This history should be infrastructure the owner benefits from without
having to understand it. A nontechnical owner should be able to ask what
changed last week, or undo something, without learning version-control
concepts.

Distribution is a separate concern from history. Sharing a Living App
requires a way to move it between people, and discovery requires a place
to find what others have published. Conceptually:

-   **evolutionary history** --- the accumulated record of change;
-   **transport** --- how a Living App travels between owners;
-   **snapshot format** --- the portable representation itself;
-   **runtime** --- the environment in which a Resident operates;
-   **future AWORG Hub** --- discovery, reputation, and possibly
    commerce.

Existing version-control and code-hosting infrastructure is the obvious
starting substrate, and there is no reason to rebuild source hosting.
But AWORG should not become permanently dependent on any single host or
network. Snapshots should remain transportable through alternative
hosts, private servers, object storage, local files, or future
registries.

## 13. Open Source and Licensing Direction

The project does not need to be open source merely because users can
receive source code.

One possible future strategy is:

-   AWORG runtime: proprietary or source-available;
-   snapshot specification: open;
-   SDKs/integrations: potentially open source;
-   user-created Living Apps: creator-controlled licensing;
-   marketplace/cloud services: proprietary.

No final licensing decision has been made.

The architectural boundary between the AWORG runtime and the user-owned
Living Workspace should be maintained regardless of licensing choice.

## 14. Why Web First

Web applications provide the best first proving ground because the
Resident can control the complete loop:

``` text
frontend <-> backend <-> database <-> filesystem <-> APIs
```

The owner can immediately preview results in the same browser interface
used to talk to the Resident.

However, **Workspace** rather than **Web** is intentionally part of
AWORG's name because generated software should not be constrained to the
web. Web-first is a starting focus, not a boundary.

## 15. Product Thesis

The central claim AWORG must prove is not:

> AI can write software.

That is already established.

The claim is:

> A persistent AI resident can inhabit a compute environment, create
> useful software for a non-programmer, continue developing it through
> conversation, observe its operation, and autonomously maintain what it
> created.

If this works reliably, the larger opportunity is:

> Anyone can create, evolve, publish, fork, inherit, and potentially
> sell sophisticated software without needing to become a programmer.

AWORG is therefore not merely an AI app builder. It is intended to
become a **runtime and ecosystem for Living Software**.
