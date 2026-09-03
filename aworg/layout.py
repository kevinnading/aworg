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
#:     | Lifecycle   +--------------------------+ Skills    |
#:     | Workspace   |                          | Tools     |
#:     |             |     Conversation         |           |
#:     +-------------+--------------------------+-----------+
#:     |            Living Log, the full width              |
#:     +----------------------------------------------------+
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
    #: column's.
    "lifecycle-height": {"default": 132, "min": 96, "max": 300},
    #: Taller than the panes below it because it is the only one with real
    #: content: four observed facts about the machine, each with what it
    #: means. The others are still saying "not yet".
    "capabilities-height": {"default": 260, "min": 90, "max": 600},
    "skills-height": {"default": 190, "min": 90, "max": 600},
    # -- the activity row above the conversation, and the split within it
    "activity-height": {"default": 186, "min": 96, "max": 600},
    #: A proportion of that row, for the same reason the columns are: Workers
    #: should not be the only thing that grows when the window does.
    "tasks-width": {"default": 45, "min": 20, "max": 75, "unit": "%"},
    # -- the console along the bottom
    "log-height": {"default": 172, "min": 90, "max": 800},
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


def resolve(stored: dict[str, float] | None = None) -> dict[str, float]:
    """The sizes in force: the defaults, with whatever the owner dragged."""
    sizes = dict(DEFAULTS)
    sizes.update(sanitize(stored or {}))
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
