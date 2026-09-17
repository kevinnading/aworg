# AWORG Website

## Website Design & Structure — Locked Decisions

> **aworg.com is the home of AWORG and the gateway to the AWORG community and ecosystem.**

This document records the website decisions currently locked in. It intentionally avoids prematurely specifying unfinished areas.

## 1. Purpose

aworg.com serves several connected purposes:

- **Explain AWORG** — introduce AWORG, the Resident concept, and Living Software.
- **Distribute AWORG** — provide the path for downloading, installing, and getting started.
- **Community Gateway** — provide a central public home for discussion and contribution.
- **Ecosystem Hub** — provide catalogs for Skills, Tools/Capabilities, Personas, and Application Snapshots.
- **Showcase Living Software** — highlight applications and projects created or maintained by Aworgs.
- **Be a Living Application** — aworg.com should itself be built, maintained, and evolved with its own Aworg, making the website evidence of the concept.

## 2. Primary Navigation

The top-level navigation is locked as:

```text
AWORG | Explore | Showcase | Learn | Community | Get AWORG | Search | Sign In
```

- **AWORG** — logo/wordmark and home link.
- **Explore** — ecosystem dropdown.
- **Showcase** — direct link to the Showcase page.
- **Learn** — learning/documentation dropdown.
- **Community** — community dropdown.
- **Get AWORG** — direct link to the download/install area.
- **Search** — global website search.
- **Sign In** — account authentication. Exact page/modal interaction remains open.

## 3. Explore

Explore is the gateway into the AWORG ecosystem.

```text
Explore
├── Skills Library
├── Tool Center
├── Personas Directory
└── Snapshot Repo
```

### Skills Library

Catalog for Skills available to Aworgs. AWORG uses the standard Agent Skills / `SKILL.md` format rather than creating a proprietary Skill format. aworg.com provides an AWORG-focused discovery and distribution hub while compatible Skills may also originate elsewhere.

### Tool Center

Catalog for executable AWORG tooling. AWORG groups related Tools into installable **Capabilities**, while individual callable functions are **Tools**. The catalog can expose both levels appropriately.

**Tool Center** is the locked navigation name.

### Personas Directory

Catalog for AWORG Personas. Personas define how a Resident behaves and presents itself and may include behavioral identity, name and voice, avatar, theme/colors, and optional background imagery.

### Snapshot Repo

Repository for snapshots of applications people have built with AWORG. Creators should eventually be able to upload and distribute application snapshots, including free or paid snapshots, community examples, and reusable starting points.

The Snapshot format, packaging, licensing, commerce, and submission process remain to be designed.

## 4. Showcase

**Showcase** is a direct top-level destination rather than a dropdown.

Its purpose is to highlight notable examples of what people are building with AWORG and what Living Software can do. It may eventually feature Living Applications, community projects, AWORG-built examples, experimental uses, and project stories.

The detailed page design remains open.

## 5. Learn

The previous **Docs** navigation item was renamed **Learn** because the section is broader than conventional technical documentation.

```text
Learn
├── About
├── History
├── Quick Start
├── How-Tos
└── Reference
```

### About

Explains what AWORG is, its core ideas, and Living Software. It can incorporate deeper conceptual material from AWORG white papers and project documentation.

### History

Documents AWORG's origins and evolution, major milestones, architectural development, and eventually the history of AWORG materially helping develop AWORG itself.

### Quick Start

The shortest practical path from discovering AWORG to running and using it.

### How-Tos

Task-oriented guides showing users how to accomplish specific things with AWORG. Tutorial-style material belongs here rather than in a separate Tutorials category.

### Reference

Detailed technical documentation: specifications, configuration, APIs, schemas, and other lookup-oriented material.

## 6. Community

The initial Community dropdown is deliberately small:

```text
Community
├── Forums
└── Contribute
```

### Forums

The primary discussion space for the AWORG community.

### Contribute

Explains how people can contribute to AWORG and its ecosystem. This may eventually cover AWORG development, Skills, Capabilities/Tools, Personas, Snapshots, documentation, and community work.

The exact contribution workflow remains open.

### Future Expansion

Possible future additions include chat/Discord, events, user groups, governance, and other community functions. These are intentionally not part of the initial navigation. In particular, an empty community chat should not be promoted before there is a reason for it to exist.

## 7. Get AWORG

**Get AWORG** directly opens the download/install area. Its purpose is to make obtaining AWORG obvious and frictionless.

The detailed download page remains to be designed.

## 8. Global Search

Search is intended to operate across the site rather than within only one section. As the ecosystem grows, results may include Skills, Tools/Capabilities, Personas, Snapshots, Showcase entries, Learn content, Forums, and future content.

Indexing, ranking, filters, and search UI remain open.

## 9. Accounts and Sign In

The site will support user accounts through **Sign In**.

Accounts will eventually support community and ecosystem functions such as publishing, contributing, managing artifacts, and potentially buying or selling ecosystem content.

Authentication UX and exact account capabilities remain open.

## 10. Blog

A Blog was discussed but is **not part of the current navigation**. It can be added when AWORG has enough news, releases, development stories, or editorial content to justify it.

## 11. Donations

A Donate button was discussed but deliberately **not added yet**. Funding/donation strategy should be determined first.

## 12. Website Philosophy

aworg.com should not become merely a static marketing site.

> **It is the public home of AWORG, the gateway to its ecosystem, and a working example of Living Software.**

The site should serve newcomers, AWORG owners, developers, creators, and the community without forcing every audience through the same path.

## 13. Current Information Architecture

```text
aworg.com
│
├── Home
├── Explore
│   ├── Skills Library
│   ├── Tool Center
│   ├── Personas Directory
│   └── Snapshot Repo
├── Showcase
├── Learn
│   ├── About
│   ├── History
│   ├── Quick Start
│   ├── How-Tos
│   └── Reference
├── Community
│   ├── Forums
│   └── Contribute
├── Get AWORG
├── Search
└── Sign In
```

## 14. Locked vs. Still To Design

### Locked

- aworg.com is both the project home and ecosystem/community gateway.
- The site should itself become a Living Application maintained with AWORG.
- Primary navigation structure.
- Explore dropdown and its four destinations.
- Showcase as a direct destination.
- Learn terminology and dropdown.
- Community initially contains Forums and Contribute.
- Get AWORG leads to downloads/install.
- Search is global.
- Sign In provides authentication.
- Blog is deferred.
- Donate is deferred.

### Still To Design

Major remaining areas include:

- homepage structure and content,
- visual identity and design system,
- ecosystem catalog layouts and artifact detail pages,
- publishing/submission workflows,
- Snapshot specification and distribution model,
- commerce for paid community artifacts,
- Showcase structure,
- Forums implementation,
- contribution workflow,
- detailed Learn content,
- download/install page,
- global search UX,
- authentication/account system,
- creator profiles,
- moderation and trust,
- ratings/reviews if desired,
- public Living Log integration,
- presentation of aworg.com's own Resident.

# Homepage Design

## Direction — Locked

The homepage introduces **Living Software** through a **permanent AI Resident**. AWORG must not be presented primarily as another chatbot, coding assistant, or prompt-to-app generator. Building is only one phase of the Resident's responsibility.

Working hero:

> **Software that lives.**
>
> AWORG gives your application a permanent AI Resident that builds it, operates it, maintains it, and evolves it.

Primary CTA: **Get AWORG**  
Secondary CTA: **See how it works**

## Homepage Layout

### 1. Global Header

Use the locked navigation:

**AWORG | Explore | Showcase | Learn | Community | Get AWORG | Search | Sign In**

Keep it restrained and product-oriented. Get AWORG receives stronger emphasis than ordinary navigation. Mobile collapses navigation while keeping AWORG identity and Get AWORG easy to reach.

### 2. Hero — Software That Lives

Lead with the working headline and Resident explanation above. The expansion **Autonomous Workspace Organism** can appear as supporting information, but should not replace the clearer Living Software explanation.

Use restrained motion suggesting persistence, continuous activity, or an intelligence inhabiting a system. Avoid robots, brains, humanoids, stock circuitry, and decorative sci-fi clutter.

### 3. Product Proof — Meet a Living Application

Show the **real AWORG interface** immediately after, or partially integrated with, the hero. It should look operational rather than like a decorative browser mockup.

Expose enough of Preview, Forever Chat, Tasks, Workers, Lifecycle, Living Log, Activities, Skills, and Tools/Capabilities to communicate that an entire software operation is taking place.

Core message:

> **One Resident. One application. One continuous relationship.**

Prefer a real or recorded AWORG session over fabricated UI when practical.

### 4. The Difference — It Doesn't Leave After the Build

Explain AWORG through the lifecycle:

**Build → Test → Deploy → Operate → Observe → Repair → Evolve → repeat**

Supporting idea:

> Traditional software waits for someone to maintain it. Living Software has a Resident.

The lifecycle must visually loop rather than terminate at deployment. This is the primary contrast with ordinary AI app builders and coding assistants.

### 5. The Resident

Introduce the Resident as the central actor: one permanent Resident responsible for one application's success, understanding its application, environment, history, current work, and mission.

Show the three activation paths:

**Owner → Resident**  
**Living Log → Resident**  
**Heartbeat → Resident**

This section may introduce Forever Chat, memory/context, Tasks, Workers, and the Resident API, but the emphasis is continuity and responsibility rather than a checklist of agent primitives.

### 6. Living Software

Give the category its own section.

> An Aworg is an autonomous AI system that inhabits a compute environment and continuously creates, operates, maintains, and evolves software within it.

Explain that AWORG can create new software or adopt existing software and is not tied to one generated stack. Runtime provides primitives, Skills provide expertise, and the Resident determines the environment.

Link deeper conceptual material to **Learn → About**.

### 7. Explore the Ecosystem

Surface all four ecosystem catalogs:

- **Skills Library** — expertise an Aworg can learn.
- **Tool Center** — executable tooling an Aworg can use.
- **Personas Directory** — identities and presentation styles for Residents.
- **Snapshot Repo** — distributable application/Aworg starting points creators can share and eventually sell.

Use real catalog cards once content exists. Featured, Trending, and New content should help the homepage feel alive as the ecosystem grows.

### 8. Showcase

Show selected Living Applications. Entries should focus not only on what was built, but what the Resident is responsible for now: operating, improving, repairing, extending, or otherwise stewarding the application.

Link to the full **Showcase**.

### 9. Dogfooding — This Website Is Living Software

aworg.com should itself be maintained by an Aworg when practical.

> **This website is a Living Application maintained by an Aworg.**

Turn this into genuine product proof. Potential public surfaces include Resident status, recent meaningful improvements, sanitized Living Log events, work cycles, version/evolution history, and provenance of Resident contributions.

Never expose private state, credentials, security-sensitive events, internal reasoning, customer/user data, or inappropriate operational detail.

### 10. Get AWORG

End the main narrative with a clear **Get AWORG** section. Eventually distinguish Community/self-hosted installation from managed or commercial offerings without making paid products necessary to understand or begin using AWORG.

Link to **Learn → Quick Start** for the complete setup process.

### 11. Footer

Use the footer as the expanded site map. Include AWORG/About/History; Explore catalogs; Learn; Showcase; Community; Get AWORG; account access; and applicable legal pages.

Blog and Donate remain deferred and should not be introduced merely to fill the footer.

## Homepage Experience Principles

The homepage should feel like **mission control for Living Software**, not a generic AI startup landing page.

Prefer real product UI, real ecosystem content, real Living Log/evolution evidence, restrained purposeful animation, strong typography/whitespace, visible persistence, and progressive disclosure.

Avoid generic AI-gradient branding, robots/brains, exaggerated autonomy claims, endless feature-card grids, fake testimonials/statistics, vague enterprise language, or presenting AWORG as merely a website generator.

Narrative progression:

**Understand it → See it → Understand the difference → Meet the Resident → Understand Living Software → Explore the ecosystem → See examples → See AWORG dogfooding itself → Get AWORG**

## Responsive Behavior

Desktop should use the real AWORG dashboard as a major visual surface. Tablet/mobile should preserve the narrative rather than squeeze the entire dashboard into an unreadable frame; use focused crops, stacked views, or controlled sequences instead.

The primary message and Get AWORG action must remain obvious at every viewport size.

## Homepage Status

**Locked direction:** Living Software is the homepage category; permanent AI Resident is the primary explanation; **Software that lives.** is the working hero; real product proof appears early; lifecycle ownership is central; ecosystem and Showcase are surfaced; aworg.com visibly dogfoods AWORG; Get AWORG is the primary conversion path.

**Still open:** final copy, logo/visual identity, typography/colors, motion language, product-demo implementation, public Living Log design, final distribution/install channels, analytics/telemetry, and detailed mobile compositions.

# Visual Identity & Design System

## Direction — Locked

AWORG's visual identity is **metallic silver + graphite/slate + electric Resident blue**.

The color metaphor is intentional:
- **Silver / metal** = software, workspace, infrastructure, structure.
- **Electric blue** = the Resident, intelligence, activity, life.
- **Graphite / slate** = the operating environment and mission-control surface.

AWORG should feel like a **precision autonomous machine with something alive inside it**.

Avoid generic purple-gradient AI branding, Earth/environmental imagery, robots, brains, humanoid AI imagery, and excessive cyberpunk decoration. Subtle cyberspace/network geometry is appropriate when it suggests computational space rather than literal planets or physical scenery.

## Theme Strategy

### Dark Mode
Use near-black graphite backgrounds, charcoal/slate raised surfaces, metallic silver structure, cool white text, electric blue Resident states/actions, restrained cyan highlights, subtle network/grid geometry, and localized blue glow around active/intelligent elements. It should remain professional rather than neon cyberpunk.

### Silver Light Mode
Light mode is **not pure white**. Use a cool silver-gray environment with layered metallic/glass surfaces, soft slate borders, darker navy/graphite typography, and the same electric Resident blue. Avoid large blank-white expanses; subtle silver gradients, cool shadows, and pale cyberspace geometry maintain depth.

## Initial Production Palette

| Token | Value | Purpose |
|---|---:|---|
| `graphite-950` | `#070B10` | Deep dark background |
| `graphite-900` | `#0B1118` | Primary dark canvas |
| `slate-850` | `#111A24` | Raised dark surfaces |
| `slate-750` | `#243342` | Muted structural surface/border |
| `steel-500` | `#7F91A3` | Secondary metallic tone |
| `silver-300` | `#B9C5D1` | Silver structure / secondary text |
| `silver-150` | `#DCE5ED` | Light borders/highlights |
| `silver-75` | `#EDF2F6` | Light-mode raised surface |
| `silver-40` | `#F4F7F9` | Light-mode canvas ceiling |
| `ice-25` | `#FAFCFD` | Rare brightest highlight |
| `resident-700` | `#075DCC` | Deep active blue |
| `resident-600` | `#087CF0` | Primary brand blue |
| `resident-500` | `#159BFF` | Active/hover highlight |
| `resident-400` | `#36B8FF` | Luminous edge |
| `resident-300` | `#76D5FF` | Ice-blue glow/highlight |
| `resident-cyan` | `#20D4E8` | Rare secondary energy accent |

Blue should be concentrated. It normally means **Resident, active state, primary action, live data, or meaningful interaction**. Success/warning/error colors remain conventional semantic UI colors rather than brand colors.

## Metallic Treatment

Express silver through value contrast, subtle cool gradients, edge highlights, restrained reflections, fine texture where appropriate, and dimensional geometry in major brand moments. Do not simulate chrome on every control. Stronger brushed-metal treatment belongs mainly in the logo, hero, and selected brand artwork.

## Typography

Use a modern technical sans-serif with excellent screen readability: geometric but not novelty sci-fi, strong numerals, useful medium/bold weights, and highly readable body text. The AWORG wordmark may use custom lettering. Small uppercase tracking can be used sparingly for section/system labels.

## Components

Panels/cards use layered graphite/slate surfaces in dark mode and silver-gray/glass-like surfaces in light mode, with restrained radii, thin cool borders, subtle depth, and minimal glow. Primary buttons use Resident blue; secondary controls remain neutral silver/graphite with blue reserved for interaction states. Icons should be simple geometric forms with consistent stroke weight.

## Cyberspace Atmosphere

Allowed background language includes sparse node/link meshes, computational grids, flowing data paths, abstract topology, subtle particles, depth layers, and faint blue points of activity. These should feel like **computational space inhabited by the Resident**.

Do not use Earth/globes, mountains/landscapes, leaves/environmental motifs, generic world-network imagery, people/community silhouettes, or decorative circuit-board clichés.

## Motion

Motion should communicate life/state: a slow Resident-core pulse, subtle data movement, lifecycle progression, quiet live indicators, activity/log events entering, smooth panel transitions, and restrained metallic light movement. Avoid constant spectacle and respect reduced-motion preferences.

## Logo Direction

The current preferred prototype family is the **metallic A / contained luminous orb**.

> **Structure containing a Resident.**

The orb represents the persistent Resident; the metallic form represents the application/workspace/system it inhabits. The family may be used for prototypes while final geometry and legal/design clearance remain separate tasks. The final logo must work dimensional or flat, dark or light, monochrome, symbol-only, wordmark lockup, and favicon/app-icon size.

## Approved Visual References

- `AWORG_Website_Visual_Reference_Dark.png`
- `AWORG_Website_Visual_Reference_Light.png`

These are **directional references, not pixel-perfect specifications**. Generated copy, sample apps, dates, slogans, navigation omissions, and incidental UI details in them are not automatically AWORG decisions. The approved qualities are the graphite/silver/blue palette, metallic structure, subdued cyberspace atmosphere, product-forward composition, and mission-control feeling.

## Visual Identity Status

**Locked:** graphite/slate + metallic silver + electric Resident blue; dark and subdued silver-light modes; blue = Resident/life/activity; silver = structure/software/workspace; cyberspace rather than Earth imagery; mission-control/precision-instrument feeling; restrained execution; real product UI as dominant proof.

**Prototype, not final:** metallic A + luminous orb logo family.

**Still to finalize:** exact production font, final logo geometry and clearance, accessibility-driven palette adjustments, component dimensions/radii/shadows, motion timings, and detailed responsive specifications.

# Remaining Site Systems — Delegated Implementation

The remaining conventional website systems may be designed by the Aworg using established modern UX conventions, while preserving all locked AWORG architecture, terminology, visual identity, and product boundaries in this brief.

## Universal Ecosystem System — Locked

Explore is one repository/catalog system with four package types: **Skill, Tool, Persona, Snapshot**.

All four use the same catalog, cards, detail-page structure, creator/profile model, publishing workflow, versioning, licensing fields, pricing/commerce framework, reviews/ratings if enabled, search/filter/sort system, install/get/buy interaction model, moderation/reporting, and discovery infrastructure.

Differences are limited to genuinely type-specific categories, metadata, payloads, validation, compatibility requirements, and backend installation/handling.

> **AWORG Package = universal ecosystem object**  
> **Package Type = Skill | Tool | Persona | Snapshot**  
> **Type Schema = genuinely type-specific metadata only**  
> **Package Payload = type-specific files/code/assets**

Do not implement four parallel marketplaces.

## Showcase

Use a conventional showcase/gallery experience for real Living Applications. Entries may show purpose, creator, screenshots/demo, Resident responsibility, relevant tags/technology, current status, related packages/Snapshots, and selected sanitized evolution history. Emphasize what the Resident continues to operate and evolve, not merely what AI generated once.

## Learn

Use conventional documentation UX beneath the locked structure: **About, History, Quick Start, How-Tos, Reference**. Provide excellent search, Markdown-first readable content, persistent navigation, deep links, copyable code, version awareness where needed, responsive layouts, and contextual cross-linking. Quick Start should optimize for the shortest successful path to running an Aworg.

## Community

Initial Community remains **Forums + Contribute**. Forums should use familiar categories, topics, replies, subscriptions/notifications, search, profiles, and moderation/reporting. Contribute should explain practical contribution paths for AWORG, documentation, packages, testing, examples, and community support. Do not manufacture empty Discord/chat/events/community surfaces.

## Get AWORG

Provide the canonical installation/distribution page. Make Community/self-hosted installation obvious, show the shortest supported install path, prerequisites, current stable version, release notes, alternate methods when necessary, and a direct Quick Start path. Future managed/commercial options may be presented separately but must not obstruct the free/self-hosted path.

Do not invent commercial entitlements or licensing language before the separate licensing decision is complete.

## Accounts & Creator Profiles

Use one account/profile system across the entire site. Creator profiles can show identity, bio/links, packages of every type, Showcase projects, and relevant community activity. Use one creator dashboard for drafts, publishing, versions, analytics, pricing where enabled, and moderation/status information.

## Publishing

Use one publishing flow for every AWORG Package:

**Create → choose type → universal metadata → type-specific metadata → package payload → validation → license/distribution/price → preview → publish**

Subsequent versions remain attached to the same package identity. Drafts, validation, moderation, deprecation, updates, and unpublishing should behave consistently across package types.

## Search

Global search spans ecosystem packages, Showcase, Learn/reference content, community content, and public creator profiles where appropriate. Results can be grouped/filterable by content type while remaining one search experience.

## Commerce

Architect the ecosystem so packages may be free or paid without making commerce mandatory. Account entitlements should preserve relevant purchase/version/license information. Processor, marketplace fee, payouts, taxes, refunds, seller verification, and regional rules remain later business/legal implementation decisions.

## Trust, Moderation & Security

Use standard marketplace/community reporting, moderation, spam/abuse controls, package provenance/version information, visible licensing, validation/scanning where technically appropriate, and removal/deprecation mechanisms. Executable Tools and Snapshots should receive stronger technical trust treatment than presentational content.

## Accessibility, Responsive Design & Performance

Target **WCAG 2.2 AA**. Support keyboard navigation, visible focus, semantic markup, contrast in both AWORG themes, reduced motion, accessible forms, screen readers, and text alternatives.

All public surfaces must work on desktop, tablet, and mobile. Complex product previews and atmospheric effects may simplify on small screens without removing essential information or actions.

Keep the site fast: optimized media, lazy loading, restrained JavaScript, caching/CDN where appropriate, efficient catalog pagination/search, and gracefully degrading cyberspace effects.

## SEO, Analytics & Privacy

Public packages, Showcase entries, Learn pages, and creator profiles should have stable canonical URLs and conventional metadata, social previews, sitemap/robots behavior, and structured data where useful.

Analytics should be privacy-conscious and limited to clear product/operational purposes. Never leak Resident private state, credentials, customer/user data, private conversations, or security-sensitive information through analytics, logs, previews, or error reporting.

## aworg.com as Living Software

aworg.com should eventually be operated as a Living Application by an Aworg. A public proof surface may expose deliberately sanitized Resident status, meaningful Living Log events, recent improvements, work-cycle/lifecycle information, version history, and provenance.

Never expose credentials, private state, customer/user information, private conversations, hidden reasoning, or security-sensitive operational detail.

## Legal Surfaces

Reserve conventional locations for the AWORG license, package licensing, Terms, Privacy, marketplace/seller terms if commerce launches, and community/acceptable-use rules where required.

The website implementation must **not choose AWORG's software license**. Exact legal content follows the separate licensing decision.

# Build Authority

This brief is intended to give the Aworg enough direction to autonomously design and implement aworg.com without pre-specifying every conventional interaction.

Where the brief is explicit, follow it. Where implementation details are unspecified, use established modern UX conventions, preserve site-wide consistency, favor simple architecture, protect accessibility/security, and avoid unnecessary custom systems.

The Resident may make implementation decisions. It may not redefine AWORG's product identity, locked information architecture, licensing, or business model without owner approval.

# Website Brief Status

The website is sufficiently specified to begin autonomous design and implementation. Remaining conventional details are intentionally delegated to the Resident.

The next separate product decision is **AWORG licensing**.
