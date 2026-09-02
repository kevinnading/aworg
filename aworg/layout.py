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


#: Each adjustable dimension, with the value it starts at and the range it may
#: be dragged through. The bounds are not decoration -- a pane dragged to
#: nothing is a pane the owner cannot find the edge of again, and one dragged
#: past the window takes the conversation off screen with it.
PANES: dict[str, dict[str, int]] = {
    #: Width of the status column, which holds everything below.
    "side-width": {"default": 400, "min": 260, "max": 900},
    #: Then the height of each pane in that column, top to bottom. Every pane
    #: is open at once rather than hidden behind a tab: this is a control
    #: room, and a control room whose instruments are stacked behind each
    #: other is a list of instruments. The column scrolls; the owner decides
    #: what deserves the room.
    "preview-height": {"default": 269, "min": 130, "max": 700},
    "lifecycle-height": {"default": 132, "min": 96, "max": 300},
    "workspace-height": {"default": 260, "min": 110, "max": 800},
    "workers-height": {"default": 172, "min": 90, "max": 600},
    "tasks-height": {"default": 160, "min": 90, "max": 600},
    "log-height": {"default": 176, "min": 90, "max": 800},
    "tools-height": {"default": 166, "min": 90, "max": 600},
    "skills-height": {"default": 176, "min": 90, "max": 600},
    "capabilities-height": {"default": 182, "min": 90, "max": 600},
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
