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
        "hint": "Where the Resident builds by default. Not a limit on where it can work.",
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
        "available": True,
        "empty": ("No tools.", "This Aworg has been built without any."),
        "blocked": None,
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
        "hint": "What this Aworg can actually do, on this machine.",
        "available": True,
        "empty": ("Nothing installed.", ""),
        "blocked": None,
    },
]

PANE_IDS = [pane["id"] for pane in PANES]


def capabilities(facts: dict[str, Any], tools: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """What the Resident can do here, as facts rather than promises.

    An owner about to ask for postgres needs to know whether this Aworg can
    install anything at all before they ask, not after it fails. Privilege
    is the first line because it is the one that decides most of the rest.
    """
    elevated = facts["elevated"]
    privilege = (
        ("Elevated", "Running with root or administrator rights.")
        if elevated
        else ("Not elevated", "Anything needing root or administrator will fail.")
        if elevated is False
        else ("Privilege unknown", "AWORG could not determine what it is allowed to do.")
    )
    items = [
        {"name": f"{facts['os']} {facts['release']}",
         "detail": f"{facts['arch']}, {facts['cpus']} CPUs", "state": "fact"},
        {"name": f"Running as {facts['user']}",
         "detail": privilege[1], "state": "ok" if elevated else "warn"},
        {"name": privilege[0], "detail": f"on {facts['hostname']}", "state": "hidden"},
    ]
    if facts["package_manager"]:
        items.append({"name": f"{facts['package_manager']} available",
                      "detail": "System packages can be installed.", "state": "ok"})
    else:
        items.append({"name": "No system package manager",
                      "detail": "Nothing on PATH to install system packages with.",
                      "state": "warn"})
    if tools:
        items.append({"name": f"Can run commands",
                      "detail": "It can act on this machine, not only describe it.",
                      "state": "ok"})
    else:
        items.append({"name": "Conversation only",
                      "detail": "No tools -- it cannot act on any of this.",
                      "state": "warn"})
    return [item for item in items if item["state"] != "hidden"]


def tool_items(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The tools as they actually are, read from the registry.

    Not a list written here and hoped to match: a pane describing tools the
    Resident does not have, or missing ones it does, is worse than no pane.
    The description is the one the model routes on, shown to the owner for
    the same reason -- if it reads vaguely here it will route vaguely there.
    """
    return [
        {"name": tool["name"],
         "detail": tool["description"].split(". ")[0].rstrip(".") + ".",
         "state": "ok"}
        for tool in tools
    ]


def describe(
    facts: dict[str, Any] | None = None,
    tools: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
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
        items: list[dict[str, Any]] = []
        if pane["id"] == "capabilities" and facts:
            items = capabilities(facts, tools)
        elif pane["id"] == "tools" and tools:
            items = tool_items(tools)

        described.append(
            {
                "id": pane["id"],
                "label": pane["label"],
                "hint": pane["hint"],
                "available": pane["available"],
                "items": items,
                "empty_heading": heading,
                "empty_detail": detail,
            }
        )
    return described
