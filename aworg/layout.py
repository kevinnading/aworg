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
PANES: dict[str, dict[str, int]] = {
    # -- the columns, left to right
    "side-width": {"default": 400, "min": 260, "max": 900},
    "faculties-width": {"default": 232, "min": 170, "max": 500},
    # -- panes within them, top to bottom (the last of each flexes)
    #
    #: The preview has no height here on purpose. It is a screen, so it keeps
    #: a screen's shape: its height follows the column's width at 16:9. One
    #: box with a fixed ratio has one dimension worth dragging, and it is the
    #: column's.
    "lifecycle-height": {"default": 132, "min": 96, "max": 300},
    "capabilities-height": {"default": 180, "min": 90, "max": 600},
    "skills-height": {"default": 190, "min": 90, "max": 600},
    # -- the activity row above the conversation, and the split within it
    "activity-height": {"default": 186, "min": 96, "max": 600},
    "tasks-width": {"default": 330, "min": 180, "max": 900},
    # -- the console along the bottom
    "log-height": {"default": 172, "min": 90, "max": 800},
}

DEFAULTS: dict[str, int] = {name: spec["default"] for name, spec in PANES.items()}


def sanitize(raw: Any) -> dict[str, int]:
    """Keep only real, in-range sizes.

    These values become CSS lengths, so they are held to being integers
    within their declared bounds rather than trusted. A browser sending
    something else -- or an older build sending a pane that no longer exists
    -- is dropped rather than refused, so one stale key cannot make an
    otherwise good layout unsavable.
    """
    if not isinstance(raw, dict):
        return {}

    clean: dict[str, int] = {}
    for name, value in raw.items():
        spec = PANES.get(name)
        if spec is None or isinstance(value, bool):
            continue
        try:
            size = int(value)
        except (TypeError, ValueError):
            continue
        clean[name] = max(spec["min"], min(spec["max"], size))
    return clean


def resolve(stored: dict[str, int] | None = None) -> dict[str, int]:
    """The sizes in force: the defaults, with whatever the owner dragged."""
    sizes = dict(DEFAULTS)
    sizes.update(sanitize(stored or {}))
    return sizes


def is_default(sizes: dict[str, int]) -> bool:
    """Whether there is anything for a reset to undo."""
    return all(sizes.get(name) == value for name, value in DEFAULTS.items())


def to_css(sizes: dict[str, int]) -> str:
    return "".join(f"  --{name}: {sizes[name]}px;\n" for name in PANES)


def describe() -> dict[str, Any]:
    """The bounds, so the interface can stop a drag at the same place."""
    return {name: dict(spec) for name, spec in PANES.items()}
