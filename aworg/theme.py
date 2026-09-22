"""The owner interface's colour scheme.

An Aworg is meant to be lived with. The owner will have this interface open
while the Resident works, for as long as the Resident is theirs -- which is the
premise of the whole product. Whether they can stand looking at it is not a
cosmetic question, and a scheme chosen once by whoever wrote the CSS is not an
answer.

So the scheme is data, not stylesheet. Every colour the interface uses is a
named token defined here; the stylesheet only ever refers to them. Adding a
theme means adding a dictionary, and nothing above this file has to change.

The token vocabulary is the ordinary one any editor exposes -- surfaces, text,
accent, status, and a syntax palette -- rather than a set invented for AWORG.
An owner who has themed an IDE already knows what these mean.

Two rules matter here:

    Every preset defines every token. A theme that is only mostly complete
    fails in the one corner nobody looked at, so the check is enforced at
    import rather than left to review.

    Every colour is validated before it reaches CSS. These values are
    interpolated into a stylesheet, so an unvalidated one is a stylesheet
    injection. Nothing that is not a plain hex colour gets through.
"""

from __future__ import annotations

import re
from typing import Any


#: A colour is a plain hex literal and nothing else. Not a CSS function, not a
#: named colour, not a custom property reference -- those are all ways to make
#: `--accent` mean something other than a colour once it reaches the browser.
HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


#: The tokens, in the order the owner interface presents them. The grouping is
#: the owner's mental model -- chrome, then the code area, then the code itself
#: -- not the order the stylesheet happens to use them in.
TOKEN_GROUPS: list[dict[str, Any]] = [
    {
        "id": "interface",
        "label": "Interface",
        "hint": "Surfaces, text, and the accent that marks what is live.",
        "tokens": [
            ("bg", "Background"),
            ("panel", "Panel"),
            ("panel-2", "Raised surface"),
            ("line", "Borders and dividers"),
            ("text", "Text"),
            ("muted", "Secondary text"),
            ("accent", "Accent"),
            ("accent-dim", "Accent, dimmed"),
            ("on-accent", "Text on accent"),
            ("owner", "Your message"),
            ("ok", "Success"),
            ("warn", "Warning"),
            ("danger", "Error"),
        ],
    },
    {
        "id": "editor",
        "label": "Code area",
        "hint": "The frame around code, rather than the code itself.",
        "tokens": [
            ("code-bg", "Code background"),
            ("code-gutter", "Line numbers"),
        ],
    },
    {
        "id": "syntax",
        "label": "Syntax",
        "hint": "How code is coloured wherever the Resident shows you any.",
        "tokens": [
            ("t-comment", "Comment"),
            ("t-string", "String"),
            ("t-number", "Number"),
            ("t-keyword", "Keyword"),
            ("t-builtin", "Built-in or type"),
            ("t-fn", "Function"),
            ("t-key", "Property"),
            ("t-decorator", "Decorator"),
            ("t-tag", "Tag"),
            ("t-attr", "Attribute"),
            ("t-variable", "Variable"),
            ("t-flag", "Command flag"),
            ("t-doctype", "Doctype"),
        ],
    },
]

#: Flat token order, derived so the groups above stay the single definition.
TOKENS: list[str] = [name for group in TOKEN_GROUPS for name, _ in group["tokens"]]


#: The presets. Each is a complete scheme; the syntax palettes are the
#: recognisable ones from the editors they are named after, because a scheme
#: that only approximates Nord is worse than one that does not claim to be it.
PRESETS: dict[str, dict[str, Any]] = {
    # The two AWORG schemes are one scheme in two lights, and the values are
    # the brand's own: graphite and slate for structure, silver for text,
    # and the Resident's blue used only where something is live or asking to
    # be pressed. Every pair here was checked against WCAG on every surface
    # it can land on -- text at 4.5:1, secondary text and accents at 3:1 --
    # rather than eyeballed, because "looks fine on my monitor" is how a
    # scheme ends up unreadable on somebody else's.
    "aworg-dark": {
        "label": "AWORG Dark",
        "dark": True,
        "note": "AWORG's own. Graphite and silver, lit by the Resident's blue.",
        "colors": {
            "bg": "#0B1118", "panel": "#111A24", "panel-2": "#172430",
            "line": "#243342", "text": "#E6EDF5", "muted": "#8FA2B5",
            "accent": "#159BFF", "accent-dim": "#0C5FB0", "on-accent": "#04121F",
            "owner": "#172232", "ok": "#3FB950", "warn": "#D29922",
            "danger": "#F85149",
            "code-bg": "#070B10", "code-gutter": "#4A5D71",
            "t-comment": "#768A9E", "t-string": "#7EE787", "t-number": "#D9A441",
            "t-keyword": "#FF7B72", "t-builtin": "#FFA657", "t-fn": "#D2A8FF",
            "t-key": "#79C0FF", "t-decorator": "#E3B341", "t-tag": "#7EE787",
            "t-attr": "#79C0FF", "t-variable": "#FFA657", "t-flag": "#A5D6FF",
            "t-doctype": "#768A9E",
        },
    },
    "aworg-light": {
        "label": "AWORG Light",
        "dark": False,
        "note": "The same scheme in daylight. Cool silver-grey, never white.",
        "colors": {
            "bg": "#F4F7F9", "panel": "#EDF2F6", "panel-2": "#E3EBF1",
            "line": "#C9D8E5", "text": "#16222E", "muted": "#55697D",
            "accent": "#075DCC", "accent-dim": "#9DC4EC", "on-accent": "#FFFFFF",
            "owner": "#E4EDF5", "ok": "#1A7F37", "warn": "#8A5A00",
            "danger": "#CF222E",
            "code-bg": "#EDF2F6", "code-gutter": "#7F91A3",
            "t-comment": "#636B75", "t-string": "#0A3069", "t-number": "#0550AE",
            "t-keyword": "#CF222E", "t-builtin": "#7B3FD6", "t-fn": "#7B3FD6",
            "t-key": "#0550AE", "t-decorator": "#953800", "t-tag": "#116329",
            "t-attr": "#0550AE", "t-variable": "#953800", "t-flag": "#0550AE",
            "t-doctype": "#636B75",
        },
    },
    "slate": {
        "label": "Slate",
        "dark": True,
        "note": "The neutral dark grey most editors open on.",
        "colors": {
            "bg": "#1e1e1e", "panel": "#252526", "panel-2": "#2d2d30",
            "line": "#3c3c41", "text": "#d4d4d4", "muted": "#8a8a8a",
            "accent": "#3d9bfd", "accent-dim": "#2a5f96", "on-accent": "#06121f",
            "owner": "#313135", "ok": "#89d185", "warn": "#cca700",
            "danger": "#f14c4c",
            "code-bg": "#1a1a1a", "code-gutter": "#6e7681",
            "t-comment": "#6a9955", "t-string": "#ce9178", "t-number": "#b5cea8",
            "t-keyword": "#569cd6", "t-builtin": "#4ec9b0", "t-fn": "#dcdcaa",
            "t-key": "#9cdcfe", "t-decorator": "#c586c0", "t-tag": "#569cd6",
            "t-attr": "#9cdcfe", "t-variable": "#9cdcfe", "t-flag": "#4ec9b0",
            "t-doctype": "#6a9955",
        },
    },
    "nord": {
        "label": "Nord",
        "dark": True,
        "note": "Cold blues, low contrast, easy for a long sitting.",
        "colors": {
            "bg": "#2e3440", "panel": "#333a47", "panel-2": "#3b4252",
            "line": "#434c5e", "text": "#eceff4", "muted": "#8b98b0",
            "accent": "#88c0d0", "accent-dim": "#5e81ac", "on-accent": "#2e3440",
            "owner": "#3b4252", "ok": "#a3be8c", "warn": "#ebcb8b",
            "danger": "#bf616a",
            "code-bg": "#292e39", "code-gutter": "#4c566a",
            "t-comment": "#616e88", "t-string": "#a3be8c", "t-number": "#b48ead",
            "t-keyword": "#81a1c1", "t-builtin": "#8fbcbb", "t-fn": "#88c0d0",
            "t-key": "#8fbcbb", "t-decorator": "#d08770", "t-tag": "#81a1c1",
            "t-attr": "#8fbcbb", "t-variable": "#d8dee9", "t-flag": "#8fbcbb",
            "t-doctype": "#616e88",
        },
    },
    "gruvbox": {
        "label": "Gruvbox",
        "dark": True,
        "note": "Warm and retro. Amber accent on brown-grey.",
        "colors": {
            "bg": "#282828", "panel": "#32302f", "panel-2": "#3c3836",
            "line": "#504945", "text": "#ebdbb2", "muted": "#a89984",
            "accent": "#fabd2f", "accent-dim": "#8f6f1c", "on-accent": "#282828",
            "owner": "#3c3836", "ok": "#b8bb26", "warn": "#fe8019",
            "danger": "#fb4934",
            "code-bg": "#1d2021", "code-gutter": "#7c6f64",
            "t-comment": "#928374", "t-string": "#b8bb26", "t-number": "#d3869b",
            "t-keyword": "#fb4934", "t-builtin": "#fabd2f", "t-fn": "#8ec07c",
            "t-key": "#83a598", "t-decorator": "#fe8019", "t-tag": "#8ec07c",
            "t-attr": "#fabd2f", "t-variable": "#83a598", "t-flag": "#8ec07c",
            "t-doctype": "#928374",
        },
    },
    "solarized-dark": {
        "label": "Solarized Dark",
        "dark": True,
        "note": "The original low-contrast scheme, in its dark form.",
        "colors": {
            "bg": "#002b36", "panel": "#01323d", "panel-2": "#073642",
            "line": "#0f4a56", "text": "#93a1a1", "muted": "#657b83",
            "accent": "#2aa198", "accent-dim": "#1d6f6a", "on-accent": "#002b36",
            "owner": "#073642", "ok": "#859900", "warn": "#b58900",
            "danger": "#dc322f",
            "code-bg": "#00252e", "code-gutter": "#586e75",
            "t-comment": "#586e75", "t-string": "#2aa198", "t-number": "#d33682",
            "t-keyword": "#859900", "t-builtin": "#268bd2", "t-fn": "#268bd2",
            "t-key": "#268bd2", "t-decorator": "#b58900", "t-tag": "#268bd2",
            "t-attr": "#93a1a1", "t-variable": "#268bd2", "t-flag": "#2aa198",
            "t-doctype": "#586e75",
        },
    },
    "solarized-light": {
        "label": "Solarized Light",
        "dark": False,
        "note": "The same palette on paper-cream. Good in a bright room.",
        "colors": {
            "bg": "#fdf6e3", "panel": "#f6efdc", "panel-2": "#eee8d5",
            "line": "#ddd6c1", "text": "#586e75", "muted": "#93a1a1",
            "accent": "#268bd2", "accent-dim": "#93b8d4", "on-accent": "#fdf6e3",
            "owner": "#eee8d5", "ok": "#859900", "warn": "#b58900",
            "danger": "#dc322f",
            "code-bg": "#f4edda", "code-gutter": "#93a1a1",
            "t-comment": "#93a1a1", "t-string": "#2aa198", "t-number": "#d33682",
            "t-keyword": "#859900", "t-builtin": "#268bd2", "t-fn": "#268bd2",
            "t-key": "#268bd2", "t-decorator": "#b58900", "t-tag": "#268bd2",
            "t-attr": "#657b83", "t-variable": "#268bd2", "t-flag": "#2aa198",
            "t-doctype": "#93a1a1",
        },
    },
    "paper": {
        "label": "Paper",
        "dark": False,
        "note": "Plain white with a blue accent, in the GitHub manner.",
        "colors": {
            "bg": "#ffffff", "panel": "#f6f8fa", "panel-2": "#eef1f4",
            "line": "#d8dee4", "text": "#1f2328", "muted": "#656d76",
            "accent": "#0969da", "accent-dim": "#a3c9f5", "on-accent": "#ffffff",
            "owner": "#eef1f4", "ok": "#1a7f37", "warn": "#9a6700",
            "danger": "#cf222e",
            "code-bg": "#f6f8fa", "code-gutter": "#8c959f",
            "t-comment": "#6e7781", "t-string": "#0a3069", "t-number": "#0550ae",
            "t-keyword": "#cf222e", "t-builtin": "#8250df", "t-fn": "#8250df",
            "t-key": "#0550ae", "t-decorator": "#953800", "t-tag": "#116329",
            "t-attr": "#0550ae", "t-variable": "#953800", "t-flag": "#0550ae",
            "t-doctype": "#6e7781",
        },
    },
    "high-contrast": {
        "label": "High Contrast",
        "dark": True,
        "note": "Maximum separation on pure black, for low vision or glare.",
        "colors": {
            "bg": "#000000", "panel": "#0d0d0d", "panel-2": "#1a1a1a",
            "line": "#6b6b6b", "text": "#ffffff", "muted": "#c9c9c9",
            "accent": "#00e5ff", "accent-dim": "#00b8d4", "on-accent": "#000000",
            "owner": "#1f1f1f", "ok": "#4dff88", "warn": "#ffd93d",
            "danger": "#ff6b6b",
            "code-bg": "#000000", "code-gutter": "#b0b0b0",
            "t-comment": "#a0a0a0", "t-string": "#7dff9a", "t-number": "#ffb86c",
            "t-keyword": "#ff79c6", "t-builtin": "#8be9fd", "t-fn": "#79c0ff",
            "t-key": "#79c0ff", "t-decorator": "#ffd93d", "t-tag": "#ff7b72",
            "t-attr": "#ffb86c", "t-variable": "#ff7b72", "t-flag": "#8be9fd",
            "t-doctype": "#a0a0a0",
        },
    },
}

DEFAULT_PRESET = "aworg-light"

#: Schemes that used to exist, and what an Aworg holding one now gets.
#:
#: Midnight was AWORG's before AWORG had a palette. Dropping it without this
#: would leave every existing Aworg storing the name of a scheme that no
#: longer exists -- rendered as the default, shown as nothing selected in the
#: picker, and with no way for the owner to tell what happened. The nearest
#: honest answer is the dark scheme that replaced it.
RENAMED_PRESETS = {"midnight": "aworg-dark"}


def _check_presets() -> None:
    """Refuse to start with an incomplete preset.

    A missing token does not fail loudly at render time -- it falls through to
    whatever the stylesheet's own :root happens to say, which usually looks
    almost right. Almost right is the expensive kind of wrong, so a preset that
    forgets a token stops the process here instead.
    """
    for preset_id, preset in PRESETS.items():
        missing = [t for t in TOKENS if t not in preset["colors"]]
        unknown = [t for t in preset["colors"] if t not in TOKENS]
        if missing or unknown:
            raise ValueError(
                f"Preset {preset_id!r} is malformed. "
                f"Missing: {missing}. Unknown: {unknown}."
            )
        for token, value in preset["colors"].items():
            if not HEX.match(value):
                raise ValueError(f"Preset {preset_id!r}: {token} is not a hex colour: {value!r}")


_check_presets()


def sanitize_overrides(raw: Any) -> dict[str, str]:
    """Keep only the overrides that are meaningful and safe.

    Anything the owner interface sends that is not a known token holding a hex
    colour is dropped rather than rejected. A stale token name from an older
    build should not make an otherwise good scheme unsavable.
    """
    if not isinstance(raw, dict):
        return {}
    return {
        token: value
        for token, value in raw.items()
        if token in TOKENS and isinstance(value, str) and HEX.match(value)
    }


def resolve(preset_id: str, overrides: dict[str, str] | None = None) -> dict[str, str]:
    """The colours actually in force: a preset, with the owner's edits on top.

    Overrides layer over the preset rather than replacing it, so changing
    preset keeps whichever individual colours the owner deliberately chose.
    Undoing one is a matter of removing it, not of remembering what it was.
    """
    base = PRESETS.get(preset_id) or PRESETS[DEFAULT_PRESET]
    fallback = PRESETS[DEFAULT_PRESET]["colors"]
    colors = {token: base["colors"].get(token, fallback[token]) for token in TOKENS}
    colors.update(sanitize_overrides(overrides or {}))
    return colors


def declarations(colors: dict[str, str]) -> str:
    """The colour tokens as CSS declarations, without the enclosing rule.

    Kept separate from the rule so that the layout's tokens can join them in
    a single :root block. Two blocks would work, but they would also invite
    the two to be served as two stylesheets, and a browser holding the
    colours but not yet the proportions paints a half-configured interface.
    """
    return "".join(f"  --{token}: {colors[token]};\n" for token in TOKENS)


def describe() -> list[dict[str, Any]]:
    """The presets as the owner interface lists them, each with a preview.

    The preview colours are the five that tell the schemes apart at a glance;
    the picker shows those rather than a name alone, because nobody chooses a
    colour scheme by reading.
    """
    return [
        {
            "id": preset_id,
            "label": preset["label"],
            "dark": preset["dark"],
            "note": preset["note"],
            "swatches": [
                preset["colors"][token]
                for token in ("bg", "panel-2", "accent", "t-keyword", "t-string")
            ],
        }
        for preset_id, preset in PRESETS.items()
    ]
