"""Where the owner has put the walls.

The Home screen is the room the owner works in, and the right proportions
depend on what they are doing. Watching an application run wants a tall
preview; reading a long reply wants a wide conversation; going through what
the Resident has built wants neither. One fixed arrangement cannot be right
for all three, and a layout that resets every time the page loads is not a
layout the owner chose -- it is one they keep re-choosing.

So the sizes are state, exactly like the colour scheme, and kept in the same
place for the same reasons: they survive a restart, they follow the owner to
whichever browser they open the Aworg from, and they are applied before the
first paint so nothing jumps into position afterwards.

The defaults are the arrangement AWORG has always opened on. Resetting the
view returns to precisely that, which is the only thing that makes a reset
button trustworthy.
"""

from __future__ import annotations

from typing import Any


#: Every adjustable dimension of the Home screen: the value it starts at, and
#: the range it may be dragged through. The bounds are not decoration -- a
#: pane dragged to nothing is a pane the owner cannot find the edge of again,
#: and one dragged past the window takes the conversation off screen with it.
#:
#: The arrangement these describe:
#:
#:     +-------------+--------------------------+-----------+
#:     | Application | Tasks     |   Workers    | Capabil.  |
#:     | Lifecycle   +--------------------------+           |
#:     | Workspace   |                          | Skills    |
#:     |             |     Conversation         |           |
#:     +-------------+--------------------------+-----------+
#:     |     Living Log      |     Activities               |
#:     +----------------------------------------------------+
#:
#: The console is split rather than being the Living Log alone. What is
#: happening and what has happened are different questions, and the pair
#: reads as a pair: an Activity that mattered becomes a log entry, and the
#: owner can watch that happen from left to right.
#:
#: The workspace and the conversation hold the middle, because that is where
#: the work happens. What the Resident can do is held at the right edge: it
#: changes least and is glanced at rather than worked in. What it is doing
#: sits directly above the conversation, because that is what the owner is
#: talking to it about. The log runs the width of the screen underneath
#: everything, the way a console does, because it reports on all of it.
#:
#: The last pane in a column takes whatever height is left rather than
#: carrying its own, so a column always fills exactly. The preview takes its
#: height from this column's width instead, to hold 16:9.
#: Widths are proportions, not pixels. A wider window should be a wider
#: everything -- when the columns were fixed, every pixel a bigger screen
#: gained went to the conversation and the panes stayed the size they were on
#: a laptop. Heights stay in pixels: a taller screen does not make a log worth
#: more rows, and the pane at the foot of each column already absorbs the
#: slack.
PANES: dict[str, dict[str, Any]] = {
    # -- the columns, left to right. The conversation is not listed because it
    #    is the remainder: 33 + 27 leaves it 40, and it stays whatever is left
    #    over as the other two are dragged.
    "side-width": {"default": 33, "min": 15, "max": 55, "unit": "%"},
    "faculties-width": {"default": 27, "min": 12, "max": 45, "unit": "%"},
    # -- panes within them, top to bottom (the last of each flexes)
    #
    #: The preview has no height here on purpose. It is a screen, so it keeps
    #: a screen's shape: its height follows the column's width at 16:9. One
    #: box with a fixed ratio has one dimension worth dragging, and it is the
    #: column's. The Lifecycle rides under it as a row and has no height of
    #: its own either, which is why "lifecycle-height" is gone from here --
    #: sanitize drops a stored one, so an owner who had dragged it loses a
    #: setting rather than a working interface.
    #: The observed facts about this machine. Read once and then glanced at,
    #: so it sits above the things the owner actually operates.
    "system-height": {"default": 150, "min": 80, "max": 500},
    #: Smaller than it was, because it no longer carries the machine facts as
    #: well -- those moved to System, and leaving this at the height it
    #: needed when it held both would squeeze Skills to nothing.
    "capabilities-height": {"default": 230, "min": 90, "max": 700},
    "skills-height": {"default": 120, "min": 80, "max": 600},
    # -- the activity row above the conversation, and the split within it
    "activity-height": {"default": 186, "min": 96, "max": 600},
    #: A proportion of that row, for the same reason the columns are: Workers
    #: should not be the only thing that grows when the window does.
    "tasks-width": {"default": 45, "min": 20, "max": 75, "unit": "%"},
    # -- the console along the bottom
    "log-height": {"default": 172, "min": 90, "max": 800},
    #: The split within the console. A proportion rather than pixels, for the
    #: same reason the columns are: on a wide screen both halves should be
    #: wider, not just the one that happens to flex. Slightly under half,
    #: because Activities carries a line per running tool and the Living Log
    #: carries wrapped sentences.
    "log-width": {"default": 46, "min": 20, "max": 80, "unit": "%"},
}

DEFAULTS: dict[str, float] = {name: spec["default"] for name, spec in PANES.items()}


def unit_of(name: str) -> str:
    return PANES[name].get("unit", "px")


def sanitize(raw: Any) -> dict[str, float]:
    """Keep only real, in-range sizes.

    These values become CSS lengths, so they are held to being numbers within
    their declared bounds rather than trusted. A browser sending something
    else -- or an older build sending a pane that no longer exists -- is
    dropped rather than refused, so one stale key cannot make an otherwise
    good layout unsavable.

    Pixels stay whole; proportions keep one decimal, because one percent of a
    wide window is fifteen pixels and a drag that can only land on whole
    percents does not feel like dragging.
    """
    if not isinstance(raw, dict):
        return {}

    clean: dict[str, float] = {}
    for name, value in raw.items():
        spec = PANES.get(name)
        if spec is None or isinstance(value, bool):
            continue
        try:
            size = float(value)
        except (TypeError, ValueError):
            continue
        # NaN and the infinities are floats and would survive the clamp --
        # int(inf) then raises, and NaN loses every comparison, so a window
        # dragged to either would take the whole request down.
        if size != size or size in (float("inf"), float("-inf")):
            continue
        size = max(spec["min"], min(spec["max"], size))
        clean[name] = round(size, 1) if unit_of(name) == "%" else int(size)
    return clean


#: Panes whose stored heights stop meaning anything once the column they
#: sit in gains or loses a member, keyed by the pane whose arrival changed
#: it. Sizes are saved per pane, not per column, so a column that grows a
#: third pane keeps two saved heights that now add up to more than there is
#: -- which is exactly how Skills ended up 28 pixels tall and overflowing.
SUPERSEDED_BY = {
    "system-height": ("capabilities-height", "skills-height"),
}


def _heal(stored: dict[str, float]) -> dict[str, float]:
    """Drop saved heights that were measured against a different column.

    A layout saved when a column had two panes cannot be honoured once it has
    three: the arithmetic no longer closes, and the pane at the foot absorbs
    a negative remainder. The owner's drags are theirs, but they were drags
    on an arrangement that no longer exists, so the affected column goes back
    to defaults rather than staying broken.

    Detected by absence: if the new pane has no saved height, this layout
    predates it. Nothing else in the file is touched, so a column the owner
    tuned elsewhere keeps exactly what they set.
    """
    healed = dict(stored)
    for arrival, affected in SUPERSEDED_BY.items():
        if arrival not in healed and any(name in healed for name in affected):
            for name in affected:
                healed.pop(name, None)
    return healed


def resolve(stored: dict[str, float] | None = None) -> dict[str, float]:
    """The sizes in force: the defaults, with whatever the owner dragged."""
    sizes = dict(DEFAULTS)
    sizes.update(sanitize(_heal(stored or {})))
    return sizes


def is_default(sizes: dict[str, float]) -> bool:
    """Whether there is anything for a reset to undo."""
    return all(sizes.get(name) == value for name, value in DEFAULTS.items())


def to_css(sizes: dict[str, float]) -> str:
    return "".join(f"  --{name}: {sizes[name]}{unit_of(name)};\n" for name in PANES)


def describe() -> dict[str, Any]:
    """The bounds and units, so the interface can stop a drag where the server
    would, and knows whether it is dragging pixels or a share of the window."""
    return {name: {"unit": "px", **spec} for name, spec in PANES.items()}
