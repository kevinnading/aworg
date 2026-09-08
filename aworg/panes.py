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
        # Sits beside the Living Log, and the pairing is the point: one says
        # what is happening, the other says what happened and mattered.
        # Neither answers the other's question, and a single pane trying to
        # do both would be a feed the owner cannot read either way.
        "id": "activities",
        "label": "Activities",
        "hint": "What the Resident is doing at this moment.",
        "available": True,
        "empty": ("Nothing running.",
                  "Tool calls and other work appear here while they happen."),
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
        "hint": "What this Aworg can do: its Tools, and what this machine has.",
        "available": True,
        "empty": ("Nothing installed.", ""),
        "blocked": None,
    },
]

PANE_IDS = [pane["id"] for pane in PANES]


def capabilities(
    facts: dict[str, Any], registry: Any = None, enabled: Any = None
) -> list[dict[str, Any]]:
    """What the Resident can do here, as facts rather than promises.

    Two registers in one pane, and they answer different halves of the same
    question. The installed Capabilities are what the Resident has been
    *granted* -- its Tools, grouped as they are packaged, each switchable by
    the owner. The machine facts are what is *present* to use them on.

    Neither is sufficient alone. A Resident with a Shell capability on a
    machine with no package manager still cannot install postgres, and an
    owner who can see only one of those two things cannot tell why. So they
    sit together, marked by `kind` so the interface can keep them visually
    distinct.

    An owner about to ask for postgres needs to know whether this Aworg can
    install anything at all before they ask, not after it fails. Privilege
    is the first line of the facts because it decides most of the rest.
    """
    items: list[dict[str, Any]] = []

    for capability in (registry.capabilities() if registry else []):
        on = enabled(capability.id) if enabled else True
        tools = [
            {"name": spec.name, "description": spec.description}
            for spec in capability.tools
        ]
        items.append({
            "kind": "capability",
            "id": capability.id,
            "name": capability.label,
            "detail": capability.description,
            "state": "ok" if on else "off",
            "enabled": on,
            "builtin": capability.builtin,
            "tools": tools,
            # A tool file that would not parse is named rather than merely
            # absent. "Nothing here" and "one of these is broken" are
            # different facts and the owner is owed the right one.
            "broken": [
                {"name": name, "detail": reason}
                for name, reason in sorted(capability.broken.items())
            ],
        })

    items.extend(_machine_facts(facts))
    return items


def _machine_facts(facts: dict[str, Any]) -> list[dict[str, Any]]:
    """What was observed about this machine, as items for the same pane."""
    elevated = facts["elevated"]
    privilege = (
        ("Elevated", "Running with root or administrator rights.")
        if elevated
        else ("Not elevated", "Anything needing root or administrator will fail.")
        if elevated is False
        else ("Privilege unknown", "AWORG could not determine what it is allowed to do.")
    )
    items = [
        {"kind": "fact", "name": f"{facts['os']} {facts['release']}",
         "detail": f"{facts['arch']}, {facts['cpus']} CPUs", "state": "fact"},
        {"kind": "fact", "name": f"Running as {facts['user']}",
         "detail": privilege[1], "state": "ok" if elevated else "warn"},
        {"kind": "fact", "name": privilege[0],
         "detail": f"on {facts['hostname']}", "state": "hidden"},
    ]
    if facts["package_manager"]:
        items.append({"kind": "fact", "name": f"{facts['package_manager']} available",
                      "detail": "System packages can be installed.", "state": "ok"})
    else:
        items.append({"kind": "fact", "name": "No system package manager",
                      "detail": "Nothing on PATH to install system packages with.",
                      "state": "warn"})
    return [item for item in items if item["state"] != "hidden"]


def describe(
    facts: dict[str, Any] | None = None,
    registry: Any = None,
    enabled: Any = None,
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
            items = capabilities(facts, registry, enabled)

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
