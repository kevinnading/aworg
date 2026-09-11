"""Where the Resident's application is in its life.

An owner who cannot read code has no way to tell the difference between
software that was written, software that starts, and software that was
checked. Those are very different things, and the gap between them is
exactly where a Resident that reports confidently can do the most damage.

So the stage is shown, and it is derived from evidence rather than from
anything the Resident says about itself. A stage the Resident could simply
claim to be in would be worth nothing -- the whole premise of AWORG is an
owner who cannot audit the claim.

The stages run in one direction and the application sits at exactly one of
them. Later milestones supply the evidence for the later stages; until then
an application cannot reach them, and saying so is more useful than showing
a progress bar that always looks encouraging.
"""

from __future__ import annotations

from typing import Any


#: The stages, in order. `evidence` is what has to be observably true to
#: reach a stage -- written down here because it is the part that matters,
#: and because a stage without a test for it is decoration.
STAGES: list[dict[str, str]] = [
    {
        "id": "empty",
        "label": "Nothing yet",
        "detail": "The workspace is empty.",
        "evidence": "no files in the Living Workspace",
    },
    {
        "id": "building",
        "label": "Being built",
        "detail": "The Resident has started making something.",
        "evidence": "files exist in the Living Workspace",
    },
    {
        "id": "running",
        "label": "Running",
        "detail": "The application starts and answers.",
        "evidence": "a process is up and serving",
    },
    {
        "id": "verified",
        "label": "Verified",
        "detail": "The Resident checked that it actually works.",
        "evidence": "the Resident observed the result of its own change",
    },
    {
        "id": "watched",
        "label": "Watched",
        "detail": "Reporting its own trouble, and repaired when it does.",
        "evidence": "the Living Log is connected and being inspected",
    },
    {
        "id": "published",
        "label": "Published",
        "detail": "Packaged as a snapshot someone else could run.",
        "evidence": "a snapshot has been exported",
    },
]

STAGE_IDS = [stage["id"] for stage in STAGES]

#: The furthest stage anything can currently produce evidence for. Stages
#: past this are shown as out of reach rather than merely not yet achieved --
#: an owner should be able to tell "my application has not got there" apart
#: from "nothing could have got there yet".
#:
#: This was "building" for as long as nothing observed a running process, and
#: then "running" once AWORG held the processes the Resident starts and could
#: see one was alive. It reaches "verified" now that AWORG fetches the served
#: application itself and can tell that the thing answering is the thing as
#: it currently stands. "Watched" waits on something inspecting the Living
#: Log on a schedule; "published" on snapshots, which are not this milestone.
REACHABLE_THROUGH = "verified"


def assess(
    workspace_has_files: bool,
    serving: dict[str, Any] | None = None,
    answered: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Which stage the application is at, and why.

    Takes observations rather than consulting the world itself, so that the
    rule stays testable and the caller stays responsible for looking.

    `serving` is a process AWORG started that is still alive and answering on
    a port, or None. It is evidence rather than testimony -- the Resident
    saying it started a server does not move this, and cannot, which is the
    whole reason the stage is derived here instead of being reported.

    `answered` is the same argument one step further on. A running process is
    not a working application: it proves something bound a port, not that the
    thing the Resident just changed still does its job. So this is AWORG's
    own fetch of the served application, made *after* the most recent change
    to the workspace -- which is what turns "it is up" into "it is up, and it
    is up as it now stands". A check made before the change would be a check
    of the previous application.

    Note that this can move backwards, and should. Break the application and
    the next fetch fails; the stage drops to running and the owner sees it
    without anyone having to notice and say so.
    """
    if serving and answered:
        current = "verified"
        reason = (
            f"AWORG fetched it on port {serving.get('port')} after the last "
            f"change and got {answered.get('status')}."
        )
    elif serving:
        current = "running"
        reason = (
            f"{serving.get('label') or 'A process'} has been up for "
            f"{serving.get('uptime', 0):.0f}s on port {serving.get('port')}."
        )
    elif workspace_has_files:
        current = "building"
        reason = "There are files in the Living Workspace."
    else:
        current = "empty"
        reason = "The Living Workspace is empty."

    horizon = STAGE_IDS.index(REACHABLE_THROUGH)
    index = STAGE_IDS.index(current)

    return {
        "current": current,
        "reason": reason,
        "stages": [
            {
                **stage,
                "state": (
                    "done" if position < index
                    else "current" if position == index
                    else "unreachable" if position > horizon
                    else "ahead"
                ),
            }
            for position, stage in enumerate(STAGES)
        ],
    }
