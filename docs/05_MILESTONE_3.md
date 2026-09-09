# AWORG Milestone 3

> **Status: met.** Measured against the criterion at the foot of this file
> rather than by feel. Asked for a three-page website, the Resident planned
> it, delegated the writing, started a server, and dispatched a checker that
> made three HTTP requests and got three 200s. The Application pane showed
> the running site and the Lifecycle stepper read *Running* — derived from a
> process AWORG could see, not from anything the Resident said. Separately,
> given a script with a NameError planted in it, the checker ran it and
> reported the failure with the right cause rather than rubber-stamping it.
>
> Three of the five things this file explicitly did **not** require are also
> built, because the work needed them sooner than expected: delegation to
> temporary workers, a plan the Resident keeps, and enough autonomy to work
> that plan without being prompted per step. The two that remain are the
> Living Log and self-directed repair — and those are the MVP's central
> claim rather than a fourth milestone's worth of polish.
>
> This file stays as written. It is a statement of intent, and rewriting it
> to match what got built would destroy the only record of what was aimed at.
> Current state lives in the README; settled decisions live in
> [06_ARCHITECTURE.md](06_ARCHITECTURE.md).

## Goal

Give the Resident hands:

> **The Resident can create, inspect, change, and run things inside its
> Living Workspace, and can tell whether what it did actually worked.**

This is the milestone where a Resident that can talk becomes a Resident
that can build. Everything before it was preparation.

## The Experience

The owner asks for something. The Resident does it.

The owner watches it happen — files appearing in the workspace, work
proceeding, the Resident saying what it is doing as it does it. When it
finishes, it reports what it made and why, in language that assumes no
technical knowledge.

The owner should never need to know how any of it was carried out. They
should only ever need to know what happened, and be able to look for
themselves if they want to.

## Authority and Its Boundary

Inside the Living Workspace the Resident has broad authority. It is the
Resident's territory, and it should be able to work there without asking
permission for every ordinary act.

Outside the workspace it has none. AWORG itself is not the Resident's to
modify, and the owner's private state is not its to touch except where
that is the explicit point of a request.

This boundary is what makes broad authority safe to grant. It should be
enforced structurally rather than trusted to the Resident's good
judgement, because a boundary that depends on the Resident behaving well
is not a boundary.

## Verification Is the Real Work

The hard part of this milestone is not doing things. It is knowing
whether they worked.

A Resident that makes a change and declares success without checking is
worse than one that does nothing, because it quietly damages what it was
asked to improve while reporting that all is well. The owner cannot
catch this — that is the whole premise of AWORG.

So the Resident must, as a matter of habit:

- observe the actual result of what it did rather than assume it;
- notice when something did not work and say so plainly;
- distinguish what it verified from what it merely believes;
- prefer checking twice over reporting confidently.

This is the same instinct the autonomous repair loop will later depend
on entirely. It should be built into the Resident's character here, in
the first milestone where it can act at all, rather than added later as
a feature. A Resident that learns to act carelessly first will not
become careful afterwards.

## Showing the Work

The owner should be able to see what the Resident is doing, not only
read what it says afterwards.

Activity belongs in the interface as it happens: what is being worked
on, what was changed, what succeeded and what did not. The workspace
listing already reflects changes as they occur; the Resident's own
account of its actions should sit alongside that.

Honest reporting matters more than impressive reporting. A Resident that
says "I tried this and it did not work" is far more valuable than one
that narrates confident progress.

## Failure Is Normal

Things will not work. Commands will fail, assumptions will be wrong,
something will be missing.

The Resident should treat this as ordinary rather than exceptional —
investigate, adjust, try again, and involve the owner when it is genuinely
stuck rather than when it is merely inconvenienced.

How the Resident behaves when things go wrong is most of what determines
whether an owner trusts it. That behaviour is established here.

## What This Milestone Does Not Require

Not required yet:

- autonomous work with no owner present;
- the Living Log;
- self-directed repair;
- delegation to temporary workers;
- any judgement about which failures deserve autonomous attention.

Those belong to the MVP's central loop. This milestone establishes that
the Resident can act deliberately and verify honestly. Autonomy without
those two things would be a liability.

## Milestone 3 Is Complete When

An owner can ask the Resident for something real, watch it build that
thing in the Living Workspace, see it run, and trust the Resident's
account of what happened — because the Resident checked rather than
assumed, and said so when it did not work.

## What Comes Next

With a Resident that can act and verify, the remaining distance to the
MVP is the **Living Log** and the **autonomous repair loop**: software
that reports its own trouble, and a Resident that notices and responds
without being asked.

That is the point where AWORG's central claim is either proven or not.
