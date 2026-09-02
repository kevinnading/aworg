"""The status column: what the owner can watch.

The white paper describes the long-term interface as a control room. This is
the register of what is in it -- one entry per pane, in the order they are
stacked, each saying what it holds and what it says while it holds nothing.

Most of these panes are empty today, and several of them are for abilities
the Resident does not have yet. They are here anyway, for the reason the
Living Workspace pane was here a milestone before the Resident could write a
file: an owner should be able to see the shape of what they have been given,
including the parts not yet filled in. A pane that appears the day a feature
ships is a pane the owner has to discover; one that has been sitting there
saying "not yet" is one they already know the meaning of.

The rule for the empty text is that it must be true and specific. "No
workers running" is a fact. "Your Resident cannot delegate work yet" is a
different fact, and the owner is owed whichever one applies -- an empty pane
that could mean either is worse than no pane.
"""

from __future__ import annotations

from typing import Any


#: Every pane in the status column, top to bottom.
#:
#: `available` is whether the underlying ability exists at all yet. When it
#: is False the pane shows `blocked` -- what the Resident cannot do and when
#: that changes. When it is True but the pane is empty, it shows `empty` --
#: the ordinary "nothing here right now".
PANES: list[dict[str, Any]] = [
    {
        "id": "workspace",
        "label": "Living Workspace",
        "hint": "Everything the Resident has made.",
        "available": True,
        "empty": ("Nothing here yet.",
                  "Your Resident cannot create files until it is given tools "
                  "and the ability to act."),
        "blocked": None,
    },
    {
        "id": "workers",
        "label": "Workers",
        "hint": "Temporary sub-agents the Resident has put to work.",
        "available": False,
        "empty": ("No workers running.", ""),
        "blocked": ("No workers running.",
                    "Your Resident works alone for now. Delegating bounded "
                    "work to temporary workers comes with the autonomous loop."),
    },
    {
        "id": "tasks",
        "label": "Tasks",
        "hint": "What the Resident is doing and what it means to do next.",
        "available": False,
        "empty": ("Nothing in progress.", ""),
        "blocked": ("Nothing in progress.",
                    "Your Resident cannot act yet, so it has nothing to be "
                    "part-way through."),
    },
    {
        "id": "log",
        "label": "Living Log",
        "hint": "What the running application reports about itself.",
        "available": False,
        "empty": ("Nothing reported.", ""),
        "blocked": ("Nothing reported.",
                    "The Living Log is the channel an application uses to tell "
                    "the Resident it is in trouble. Nothing is running to use it."),
    },
    {
        "id": "tools",
        "label": "Tools",
        "hint": "What the Resident can directly do.",
        "available": False,
        "empty": ("No tools.", ""),
        "blocked": ("No tools yet.",
                    "Reading and writing files, running commands, and the rest "
                    "of the Resident's hands arrive in Milestone 3."),
    },
    {
        "id": "skills",
        "label": "Skills",
        "hint": "Procedures the Resident knows how to carry out.",
        "available": False,
        "empty": ("No skills installed.", ""),
        "blocked": ("No skills yet.",
                    "A skill is a way of doing something well, kept so it can "
                    "be reused. There is nothing to keep until the Resident "
                    "can do things."),
    },
    {
        "id": "capabilities",
        "label": "Capabilities",
        "hint": "The sum of what this Aworg is able to do.",
        "available": False,
        "empty": ("Nothing installed.", ""),
        "blocked": ("Conversation only.",
                    "Capabilities gather the tools, skills, and automations "
                    "an Aworg has. Yours has none of them yet -- it can talk, "
                    "and that is all."),
    },
]

PANE_IDS = [pane["id"] for pane in PANES]


def describe() -> list[dict[str, Any]]:
    """The panes as the owner interface renders them.

    The two empty texts collapse into the one that applies here rather than
    in the browser, so that "what this pane says when it has nothing" has a
    single answer living next to the pane's definition.
    """
    described = []
    for pane in PANES:
        if pane["available"]:
            heading, detail = pane["empty"]
        else:
            heading, detail = pane["blocked"] or pane["empty"]
        described.append(
            {
                "id": pane["id"],
                "label": pane["label"],
                "hint": pane["hint"],
                "available": pane["available"],
                "items": [],
                "empty_heading": heading,
                "empty_detail": detail,
            }
        )
    return described
