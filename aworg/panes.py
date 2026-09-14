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

from . import host


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
        "hint": "Workers running right now. They appear when dispatched and go when done.",
        "available": True,
        "empty": ("No workers running.",
                  "Workers appear here while they are working and leave when "
                  "they finish. What kinds of worker exist is set in "
                  "Settings, under Model Pool."),
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
        "hint": "What happened, and mattered.",
        "available": True,
        "empty": ("Nothing has happened yet.",
                  "Work that is worth remembering is written here and stays "
                  "-- a program that stopped on its own, something that "
                  "failed, a plan finished, a Capability you switched off. "
                  "What is happening right now is in Activities instead."),
        "blocked": None,
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
        "id": "environment",
        "label": "Environment",
        # Named for what it holds rather than for half of it. "System"
        # covers the machine and says nothing about the workspace, the
        # interpreter or the shell -- which are the items here that have
        # actually changed what a Resident did.
        "hint": "Where this Aworg is, and what it has to work with -- the same facts the Resident is given.",
        "available": True,
        "empty": ("Nothing observed.", ""),
        "blocked": None,
    },
    {
        "id": "skills",
        "label": "Skills",
        "hint": "Procedures the Resident knows how to carry out.",
        "available": True,
        "empty": ("No skills installed.",
                  "A skill is a way of doing something well, written down so "
                  "it can be reused. Put a folder with a SKILL.md in it under "
                  "skills/ in this Aworg's home."),
        "blocked": None,
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
    """What the Resident has been granted: its Capabilities and their Tools.

    Only that. This pane used to hold the machine facts as well, on the
    argument that a Shell capability and a machine with no package manager
    are two halves of one question. They are -- but they are also two
    different *kinds* of thing, one the owner decides and one the owner
    merely learns, and mixing them made the pane hard to scan and gave the
    switches somewhere to hide. The facts now live in Environment.

    Each Capability carries what it costs. Tool schemas are sent on every
    single request, and the Resident's five capabilities came to more tokens
    than its entire system prompt -- so an owner leaving everything on
    forever is paying for it on every message, in a currency nobody was
    showing them.
    """
    items: list[dict[str, Any]] = []

    for capability in (registry.capabilities() if registry else []):
        # Environment-embedded capabilities are machinery, not something the
        # owner installed and may switch. Delegation lives here; workers are
        # configured in their own pane, which is the control that means
        # something.
        if capability.internal:
            continue
        # A required capability is on regardless of what the store says --
        # including an Aworg whose owner switched Filesystem off before it
        # stopped being switchable.
        on = True if capability.required else (enabled(capability.id) if enabled else True)
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
            #: No switch. The interface shows what it is and what it costs,
            #: and offers nothing to press -- see Capability.required.
            "required": capability.required,
            "builtin": capability.builtin,
            "tools": tools,
            # What offering this costs on every request, whether or not the
            # Resident reaches for it. Shown so that "enable everything" is
            # a decision with a visible price rather than a free default.
            "tokens": schema_tokens(capability.tools),
            # A tool file that would not parse is named rather than merely
            # absent. "Nothing here" and "one of these is broken" are
            # different facts and the owner is owed the right one.
            "broken": [
                {"name": name, "detail": reason}
                for name, reason in sorted(capability.broken.items())
            ],
        })

    return items


def system(
    facts: dict[str, Any], workspace: Any = None
) -> list[dict[str, Any]]:
    """Where this Aworg is, and what was found around it at startup.

    Its own pane now rather than the tail of Capabilities. These are facts
    the owner *learns*, where a Capability is a decision the owner *makes*,
    and a pane that mixes the two invites reading a fact as a control.

    An owner about to ask for postgres needs to know whether this Aworg could
    install anything at all before they ask rather than after it fails, which
    is why this is on screen instead of only in the Resident's prompt.

    The workspace comes first, and it is the one item here that was chosen
    rather than observed. It earns the place because it answers the question
    an owner asks before any of the others: where does the thing being built
    actually end up on my disk. It was in nothing the owner could see, and
    the Resident could not see it either -- which is how Residents came to
    treat AWORG's own source directory as the project and write into it.
    Fixing the prompt without putting the same fact on screen would have left
    the owner unable to check the answer the Resident was now being given.

    Only the location. What is *in* it is the Living Workspace pane's
    question, and two panes counting the same files is two panes that can
    disagree.
    """
    return _machine_facts(facts, workspace)


#: Characters per token, matching Resident.CHARS_PER_TOKEN. Duplicated
#: rather than imported because panes.py has no business importing the
#: Resident, and the number is a property of the tokenizer rather than of
#: either module.
CHARS_PER_TOKEN = 3.6


def schema_tokens(specs: list[Any]) -> int:
    """What a set of tools costs to offer, in tokens, per request.

    Estimated from the JSON that actually goes on the wire. Approximate, and
    labelled as such in the interface -- the point is the order of magnitude,
    which is what tells an owner that leaving Browser enabled all year is not
    free.
    """
    import json

    payload = json.dumps([
        {
            "name": spec.name,
            "description": spec.description,
            "inputSchema": spec.input_schema,
        }
        for spec in specs
    ])
    return int(len(payload) / CHARS_PER_TOKEN)


def _machine_facts(facts: dict[str, Any], workspace: Any = None) -> list[dict[str, Any]]:
    """The environment, exactly as the Resident is given it.

    Built from host.environment rather than assembled here, and that is the
    point of the pane. An owner looking at this is looking at the Resident's
    own briefing, item for item and in the same order -- so when it does
    something that makes no sense, they can see whether it was told something
    wrong or understood something wrong.

    A second rendering of the same facts would drift, and a pane that drifts
    from the prompt is worse than no pane: it would let an owner rule out a
    cause that was in fact the cause.
    """
    elevated = facts.get("elevated")
    # Only one of these is a condition rather than a reading. Not being
    # elevated is not a fault -- most Aworgs should not be -- but it is the
    # line that explains a whole class of refusals, so it is marked.
    states = {
        "Privileges": "ok" if elevated else "warn" if elevated is False else "warn",
        "Address": "ok" if facts.get("ip") else "warn",
    }
    return [
        {
            "kind": "fact",
            "name": label,
            "detail": value,
            "state": states.get(label, "fact"),
        }
        for label, value in host.environment(facts, workspace)
    ]


def workers(crew: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deliberately empty at rest.

    A worker is temporary: spawned for one bounded job, disposed when it
    finishes. So this pane answers "who is working for me right now", not
    "what kinds of worker exist" -- the second is configuration and belongs
    in Settings beside the models, which is where a worker's connection and
    prompt are chosen anyway.

    Listing the configured kinds here made a permanent roster out of
    something whose defining property is being temporary, and left an owner
    unable to see the thing they actually wanted: that three workers are
    running and one of them is stuck.

    The rows come from the live Activity stream rather than from here, for
    the same reason Activities does -- a pane painted from a snapshot cannot
    show work arriving and leaving.
    """
    return []


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


def skills(library: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The procedures this Aworg knows, as the pane lists them.

    The description is shown rather than truncated to a label, because the
    description is the whole of what makes a skill usable: it is what tells
    the Resident when to reach for this one, and an owner reading the pane is
    reading the same sentence the Resident reads.
    """
    return [
        {
            "kind": "skill",
            "id": skill["name"],
            "name": skill["name"],
            "detail": skill["description"],
            "state": "ok" if skill.get("enabled", True) else "off",
            "enabled": skill.get("enabled", True),
            "source": skill["source"],
            # Whether the skill's own author allows the Resident to reach
            # for it, which is a different thing from the owner's switch and
            # worth seeing before touching either.
            "model_invocable": skill.get("model_invocable", True),
            # Whether it is reaching the Resident right now, and why not if
            # it is not. A skill that has quietly retired would otherwise
            # look identical to one that is working.
            "offered": skill.get("offered", True),
            "active_while": skill.get("active_while", "always"),
            "references": len(skill["references"]),
        }
        for skill in library
    ]


def log(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The Living Log, as rows.

    Passed through nearly unchanged, which is deliberate. The judging already
    happened in journal.py; anything summarised, merged or reworded here
    would be a second opinion layered over the first, and an owner reading
    this pane is reading it precisely because they want the record rather
    than an account of it.
    """
    return [
        {
            "kind": "entry",
            "id": str(entry.get("id")),
            "level": entry.get("level") or "note",
            "category": entry.get("kind") or "aworg",
            "source": entry.get("source") or "aworg",
            "name": entry.get("summary") or "",
            "detail": entry.get("detail") or "",
            "at": entry.get("at") or "",
            "activity_id": entry.get("activity_id"),
            # Whether anything still needs doing. Notes are never open, so
            # this is narrower than "not marked resolved" -- the store
            # decides what open means and this only carries the answer.
            "open": bool(
                not entry.get("resolved")
                and (entry.get("level") in ("concern", "alarm"))
            ),
            "resolution": entry.get("resolution") or "",
            "resolved_by": entry.get("resolved_by") or "",
        }
        for entry in entries
    ]


def describe(
    facts: dict[str, Any] | None = None,
    registry: Any = None,
    enabled: Any = None,
    crew: list[dict[str, Any]] | None = None,
    plan: list[dict[str, Any]] | None = None,
    known: list[dict[str, Any]] | None = None,
    happened: list[dict[str, Any]] | None = None,
    workspace: Any = None,
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
        if pane["id"] == "capabilities":
            items = capabilities(facts or {}, registry, enabled)
        elif pane["id"] == "environment" and facts:
            items = system(facts, workspace=workspace)
        elif pane["id"] == "workers" and crew:
            items = workers(crew)
        elif pane["id"] == "tasks" and plan:
            items = tasks(plan)
        elif pane["id"] == "skills" and known:
            items = skills(known)
        elif pane["id"] == "log" and happened:
            items = log(happened)

        entry = {
            "id": pane["id"],
            "label": pane["label"],
            "hint": pane["hint"],
            "available": pane["available"],
            "items": items,
            "empty_heading": heading,
            "empty_detail": detail,
        }
        # What this pane's contents cost the Resident on every message.
        #
        # Capabilities has carried a price per capability for a while, on the
        # argument that an owner leaving everything switched on is paying for
        # it in a currency nobody was showing them. The environment is the
        # other thing sent with every request, and it had no price on it at
        # all -- which is how it grew to more than three times what its own
        # docstring claimed without anyone noticing.
        #
        # Measured from the block that actually goes, not estimated from the
        # readings above it, so the number cannot drift from the thing it is
        # describing.
        if pane["id"] == "environment" and facts:
            entry["tokens"] = int(
                len(host.summary(facts, workspace)) / CHARS_PER_TOKEN
            )
        described.append(entry)
    return described
