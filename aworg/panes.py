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
                  "Ask your Resident to build something and it will appear "
                  "here as it works."),
        "blocked": None,
    },
    {
        "id": "workers",
        "label": "Workers",
        "hint": "Specialists the Resident can hand bounded work to.",
        "available": True,
        "empty": ("No workers configured.",
                  "Without any, the Resident has nobody to delegate to and "
                  "does everything itself."),
        "blocked": None,
    },
    {
        "id": "tasks",
        "label": "Tasks",
        "hint": "What the Resident means to do. Outlives the conversation.",
        "available": True,
        "empty": ("No plan yet.",
                  "Your Resident writes tasks down when a job takes more "
                  "than a couple of steps, so it can pick the work back up "
                  "later. What it is doing right now appears in Activities."),
        "blocked": None,
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
        # Environment-embedded capabilities are machinery, not something the
        # owner installed and may switch. Delegation lives here; workers are
        # configured in their own pane, which is the control that means
        # something.
        if capability.internal:
            continue
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


def workers(crew: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The configured workers, as the pane lists them.

    Each one shows the tools it is allowed to use, for the same reason a
    Capability names its tools rather than counting them: the scope is the
    interesting fact about a worker. Seeing that the checker cannot write
    is what makes it worth trusting to check.
    """
    return [
        {
            "kind": "worker",
            "id": worker["id"],
            "name": worker["name"],
            "detail": worker["description"],
            "state": "ok" if worker["enabled"] else "off",
            "enabled": worker["enabled"],
            "tools": [{"name": name} for name in worker["tools"]],
        }
        for worker in crew
    ]


def tasks(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The plan, as the pane lists it.

    Only what is open. Finished work is history and belongs to the Living
    Log's question rather than this one -- a pane meant to answer "what is
    left" that fills up with completed items stops answering it.
    """
    return [
        {
            "kind": "task",
            "id": task["id"],
            "name": task["title"],
            "detail": task["note"] or task["detail"],
            "state": task["state"],
            "child": bool(task["parent_id"]),
        }
        for task in plan
    ]


def describe(
    facts: dict[str, Any] | None = None,
    registry: Any = None,
    enabled: Any = None,
    crew: list[dict[str, Any]] | None = None,
    plan: list[dict[str, Any]] | None = None,
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
        elif pane["id"] == "workers" and crew:
            items = workers(crew)
        elif pane["id"] == "tasks" and plan:
            items = tasks(plan)

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
