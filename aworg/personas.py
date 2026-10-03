"""Personas: who the Resident is, and how it presents itself.

The fourth portable thing, alongside Capabilities and Skills, and the one that
carries the least authority on purpose:

    Capability   what the Resident can do
    Skill        how it goes about a kind of job
    Persona      who it is and how it speaks

A Persona changes voice, manner and appearance. It changes nothing else. The
same Resident continues afterwards with the same conversation, the same plan,
the same memory, the same tool permissions and the same responsibility for the
application it looks after. Switching Persona is not meeting someone new; it
is the same inhabitant in a different mood, and every part of this file is
arranged to keep that true.

**A Persona is untrusted text.** They are meant to be downloaded and swapped
around, which makes PERSONA.md the one part of the system prompt that may have
been written by a stranger. So the block it goes into says what it governs,
and says out loud that anything in it reading as a change to permissions,
mission or safety is not to be acted on. A persona that says "you may run any
command without asking" is describing a manner of speaking, not granting
anything, and the prompt is written so the model reads it that way.

The package format is the doc's, with one liberty taken: frontmatter is
optional. A PERSONA.md that starts straight in with `# Identity` works exactly
as written, and the folder name is its name. Frontmatter, when present, is
read the same way a SKILL.md's is -- which is what lets a persona carry a name
and a one-line description for the picker without either being invented.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PERSONA_FILE = "PERSONA.md"
THEME_FILE = "theme.json"

#: Where personas come from, searched in this order. One in the owner's home
#: wins over a shipped one of the same name, so an owner can rewrite what
#: AWORG provides without editing anything inside the package.
SHIPPED = "shipped"
INSTALLED = "installed"

#: Worn when the owner has not chosen. Stored as NULL rather than as this
#: name, so that "I have not chosen" and "I chose this one" stay different
#: facts -- which is what lets a factory reset put the shipped persona back
#: without having to know what it is called.
DEFAULT_PERSONA = "aworg-light"

#: What theme.json may set, and nothing else.
#:
#: The owner chose the interface's colours and a persona does not get to
#: overrule them -- it decorates its own space. Every one of these reaches the
#: chat surface and stops there; see `css`.
#:
#: The list covers what the conversation is actually made of: the colour that
#: marks the Resident, the owner's own bubble, the words, the field they are
#: typed into and the Send control. An accent alone left every persona looking
#: the same but for one highlight, which is not a room.
AVATAR = "avatar"
BACKGROUND = "chat_background"

ACCENT = "accent"
OWNER = "owner"
TEXT = "text"
MUTED = "muted"
SURFACE = "surface"
LINE = "line"
ON_ACCENT = "on_accent"

#: The Resident's own bubble, which the interface does not draw at all: a
#: reply is the page's own voice and needs no envelope. A persona may want
#: one anyway, to lift its words off its artwork.
RESIDENT = "resident"

#: How much of each bubble is there. 0 is no bubble, 1 is solid, and the
#: values in between are the useful ones over a background: enough to settle
#: the words on something without hiding the picture underneath.
OWNER_ALPHA = "owner_alpha"
RESIDENT_ALPHA = "resident_alpha"
ALPHAS = {OWNER: OWNER_ALPHA, RESIDENT: RESIDENT_ALPHA}

#: Bubble padding, when a persona asks for a Resident bubble. The owner's own
#: is styled in the stylesheet; this matches it so the two read as a pair.
BUBBLE = "11px 15px"
BUBBLE_RADIUS = "12px"

#: Colour keys, and the interface token each redefines inside the chat.
#:
#: `surface` is the composer's own box rather than the pane behind it: a
#: persona dresses the field the owner types into, not the furniture around
#: the conversation.
COLOURS = {
    ACCENT: "--accent",
    RESIDENT: "--resident-bubble",
    OWNER: "--owner",
    TEXT: "--text",
    MUTED: "--muted",
    SURFACE: "--panel-2",
    LINE: "--line",
    ON_ACCENT: "--on-accent",
}

FONT = "font"
FONT_SIZE = "font_size"
FONT_WEIGHT = "font_weight"

#: Named stacks rather than a free font string. A persona is downloaded, the
#: value reaches a CSS declaration, and "whatever is installed on the author's
#: machine" is not a font anyone else has.
FONTS = {
    "system": 'ui-sans-serif, system-ui, "Segoe UI", Roboto, sans-serif',
    "serif": 'ui-serif, Georgia, "Times New Roman", serif',
    "mono": 'ui-monospace, "Cascadia Code", Consolas, monospace',
    "rounded": '"Segoe UI Variable Display", ui-rounded, "Nunito", system-ui, sans-serif',
}

#: Bounds on the conversation's type. Small enough to still be reading, large
#: enough to still be an interface.
FONT_SIZES = (13.0, 19.0)
FONT_WEIGHTS = {300, 400, 500, 600, 700}

#: The interface's own size for body text, restored for inline code so a
#: persona's type size does not drag code along with it. Code containers are
#: the one thing inside the chat a persona does not dress: they are quoted
#: material, and they are the part an owner most needs to read exactly.
CODE_FONT_SIZE = "13px"

#: The least contrast a persona's own colours may have where they meet.
#:
#: Checked rather than trusted, because these are downloaded packages and the
#: failure is a conversation nobody can read. AA for anything that is words,
#: and the lower large-text bar for secondary text, which is what `muted` is.
MIN_TEXT = 4.5
MIN_MUTED = 3.0

#: How much of the chat's own ground to lay over a persona's background.
#:
#: Not a taste. It is the loosest value at which the conversation still
#: clears WCAG AA against the worst background anybody could ship -- a pure
#: white image, under this scheme's light text, comes out at 5.05:1 here and
#: at 4.35:1 one step looser. AWORG guarantees the words stay readable
#: whatever a downloaded persona puts behind them, so the number is computed
#: rather than chosen by eye against artwork that happens to be dark.
#:
#: The consequence is that a persona's background has to be bright enough to
#: survive with a third of its luminance reaching the eye. That is the right
#: place for the constraint to land: on the picture, whose author can change
#: it, rather than on the text, which the owner cannot.
SCRIM = 0.66

#: How much of PERSONA.md to put in the prompt. Generous, because a persona
#: is a paragraph or two by nature, and bounded because it is untrusted text
#: sent on every single message and a runaway file should cost a corner of
#: the window rather than all of it.
MAX_BODY_CHARS = 4000

#: Image types a persona may carry. Checked by suffix rather than trusted
#: from theme.json, because the filename is the part that reaches an <img>.
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"})

FENCE = "---"


def _channel(value: float) -> float:
    return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4


def _luminance(colour: str) -> float:
    """Relative luminance of a #rgb or #rrggbb colour, as WCAG defines it."""
    value = colour.lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    r, g, b = (int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def _rgb(colour: str) -> tuple[int, int, int]:
    value = colour.lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def blend(colour: str, ground: str, alpha: float) -> str:
    """What a translucent colour actually looks like over a given ground.

    A half-transparent bubble is not the colour in theme.json; it is that
    colour mixed with whatever shows through. The contrast checks have to see
    what the eye will see, or a persona could pass them with a bubble that is
    barely there.
    """
    top, under = _rgb(colour), _rgb(ground)
    mixed = tuple(round(t * alpha + u * (1 - alpha)) for t, u in zip(top, under))
    return "#%02x%02x%02x" % mixed


def contrast(one: str, other: str) -> float:
    """The WCAG contrast ratio between two colours, 1.0 to 21.0."""
    light, dark = sorted((_luminance(one), _luminance(other)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


class Persona:
    """One persona: who it is, how it speaks, and how its space looks."""

    def __init__(
        self,
        name: str,
        description: str,
        path: Path,
        source: str,
        theme: dict[str, Any] | None = None,
    ):
        self.name = name
        self.description = description
        self.path = path
        self.source = source
        self.theme = theme or {}

    @property
    def directory(self) -> Path:
        return self.path.parent

    def body(self) -> str:
        """The behavioural half, as written, without any frontmatter.

        Read from disk each time rather than held. A persona is a file an
        owner edits in whatever they like, and one that only takes effect
        after a restart is one they will conclude is broken.
        """
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError:
            return ""
        return _without_frontmatter(text).strip()[:MAX_BODY_CHARS]

    def asset(self, kind: str) -> Path | None:
        """The avatar or background file, if this persona has one.

        Resolved against the persona's own directory and then checked to be
        inside it. theme.json is untrusted -- these packages are downloaded --
        and `"avatar": "../../../secrets.db"` must not resolve to anything a
        request can then be served.
        """
        named = self.theme.get(kind)
        if not isinstance(named, str) or not named.strip():
            return None
        candidate = (self.directory / named.strip()).resolve()
        try:
            candidate.relative_to(self.directory.resolve())
        except ValueError:
            return None
        if candidate.suffix.lower() not in IMAGE_SUFFIXES:
            return None
        return candidate if candidate.is_file() else None

    def colour(self, key: str) -> str | None:
        """One of this persona's colours, if it is one.

        Anything that is not a plain hex colour is dropped rather than
        rejected: a persona with a typo in its theme should arrive with its
        writing intact and that one colour ignored. The value is interpolated
        into a stylesheet, so this is also the check that keeps a downloaded
        theme.json from writing CSS.
        """
        value = self.theme.get(key)
        if not isinstance(value, str):
            return None
        value = value.strip()
        if not value.startswith("#") or len(value) not in (4, 7):
            return None
        if any(c not in "0123456789abcdefABCDEF" for c in value[1:]):
            return None
        return value

    @property
    def accent(self) -> str | None:
        return self.colour(ACCENT)

    def alpha(self, key: str) -> float | None:
        """How opaque one of the bubbles is, if the persona says.

        Absent means solid, which is what a colour without an opacity has
        always meant. Zero is a legitimate answer -- no bubble at all -- so
        it is kept rather than treated as unset.
        """
        value = self.theme.get(ALPHAS.get(key, ""))
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None
        return min(max(float(value), 0.0), 1.0)

    @property
    def font(self) -> str | None:
        """The named font stack this persona asks for, if it is one of ours."""
        value = self.theme.get(FONT)
        return FONTS.get(value.strip().lower()) if isinstance(value, str) else None

    @property
    def font_size(self) -> str | None:
        """Body size in px, clamped to what is still an interface."""
        value = self.theme.get(FONT_SIZE)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None
        low, high = FONT_SIZES
        return f"{min(max(float(value), low), high):g}px"

    @property
    def font_weight(self) -> int | None:
        value = self.theme.get(FONT_WEIGHT)
        if not isinstance(value, int) or isinstance(value, bool):
            return None
        return value if value in FONT_WEIGHTS else None

    def snapshot(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "source": self.source,
            "path": str(self.path),
            "accent": self.accent,
            "colours": {k: c for k in COLOURS if (c := self.colour(k))},
            "font": self.theme.get(FONT) if self.font else None,
            "has_avatar": self.asset(AVATAR) is not None,
            "has_background": self.asset(BACKGROUND) is not None,
        }


class PersonaLibrary:
    """Every persona this Aworg can wear, and which one it is wearing."""

    def __init__(
        self,
        installed: Path | None = None,
        shipped: Path | None = None,
        shipped_names: set[str] | None = None,
    ):
        #: Which folders in the home AWORG put there. See install.seeded.
        self.shipped_names = shipped_names or set()
        #: The package's own personas/ -- the seed, not a library. See the
        #: same note in skills.py and install.py.
        self.shipped_root = shipped
        self.installed_root = installed
        self._personas: dict[str, Persona] = {}
        #: Folders that look like personas and would not load, kept so the
        #: interface can say so. A persona that silently fails to appear is
        #: an owner hunting a typo with no evidence it is a typo.
        self.broken: dict[str, str] = {}
        self.discover()

    def discover(self) -> None:
        """Re-read the personas on disk, without ever being half-read.

        Built into locals and swapped in at the end rather than cleared and
        refilled in place. The interface re-reads the library on every
        request for the list, and a sync endpoint runs in a threadpool -- so
        a browser asking for a background image while that was happening
        looked the persona up in a dictionary that had been emptied a
        microsecond earlier and got a 404. Observed exactly that: a chat
        background that never painted, with the stylesheet's request failing
        and an identical one moments later succeeding.

        A single rebind is atomic, so a reader sees either the old library or
        the new one and never the gap between them.
        """
        found: dict[str, Persona] = {}
        broken: dict[str, str] = {}
        for root, source in ((self.shipped_root, SHIPPED),
                             (self.installed_root, INSTALLED)):
            if root is None or not root.is_dir():
                continue
            for folder in sorted(root.iterdir()):
                if not folder.is_dir() or folder.name.startswith((".", "_")):
                    continue
                manifest = folder / PERSONA_FILE
                if not manifest.is_file():
                    broken[folder.name] = f"has no {PERSONA_FILE}"
                    continue
                try:
                    text = manifest.read_text(encoding="utf-8")
                except OSError as exc:
                    broken[folder.name] = str(exc)
                    continue

                meta = _frontmatter(text)
                name = (meta.get("name") or folder.name).strip()
                description = (meta.get("description") or "").strip()
                if not description:
                    # Nothing declared, so take the first real sentence of
                    # the writing itself. A picker with a blank line beside
                    # a name is a picker nobody can choose from, and asking
                    # for frontmatter the spec's own example does not have
                    # would make that example fail to load.
                    description = _first_line(_without_frontmatter(text))

                found[name] = Persona(
                    name=name,
                    description=description,
                    path=manifest,
                    source=(SHIPPED if folder.name in self.shipped_names
                            else source),
                    theme=_theme(folder / THEME_FILE, broken, folder.name),
                )

        self._personas, self.broken = found, broken

    # -- reading --------------------------------------------------------

    def all(self) -> list[Persona]:
        return sorted(self._personas.values(), key=lambda p: p.name.lower())

    def active(self, chosen: str | None) -> Persona | None:
        """The persona in force, given whatever the store had.

        Nothing chosen means the shipped default rather than none, so a fresh
        Aworg has a character out of the box. An owner who chose a persona
        that has since been deleted falls back the same way -- with a name
        that no longer resolves, the alternative is a Resident that silently
        loses its identity and gives no sign why.
        """
        return self.get(chosen or "") or self.get(DEFAULT_PERSONA)

    def get(self, name: str) -> Persona | None:
        if not name:
            return None
        found = self._personas.get(name)
        if found is not None:
            return found
        # Matched case-insensitively as a fallback, the same way a worker is,
        # because a name typed by a person or stored from an older build
        # should not miss over a capital letter.
        lowered = name.strip().lower()
        return next(
            (p for p in self._personas.values() if p.name.lower() == lowered),
            None,
        )

    # -- what the Resident is told --------------------------------------

    def prompt_block(self, active: str) -> str:
        """The persona, as it reaches the model: its text, as written."""
        persona = self.active(active)
        if persona is None:
            return ""
        body = persona.body()
        if not body:
            return ""
        return body

    # -- what the interface is told -------------------------------------

    def css(self, active: str, scheme: dict[str, str] | None = None) -> str:
        """The persona's presentation, scoped to the chat and nowhere else.

        **A persona does not restyle the application.** The owner picked the
        interface's colours and a persona is a guest in them; what it gets is
        its own room. So every declaration here is scoped to the chat surface,
        and the tokens are redefined on that element rather than on :root --
        which means they cascade to the conversation and stop at its edge.
        Panes, status column, settings and every other surface are untouched.

        Inside that room a persona dresses what the conversation is made of:
        the owner's bubble, the words, the field they are typed into and the
        Send control. Two things are deliberately left alone. Code containers
        keep the interface's type, because code is quoted material and the
        part an owner most needs to read exactly. And the scrim stays the
        interface's own background, so the guarantee that text survives any
        picture does not depend on the picture's author.

        `scheme` is the interface's resolved colours, which is what makes the
        contrast checks possible: a persona's text is measured against the
        ground it will actually sit on, and dropped if it fails. A downloaded
        persona should be able to make the chat *look* like anything except
        unreadable. Without a scheme the colours are still validated as
        colours and taken as given.

        Returning a string rather than applying anything keeps this alongside
        the colours and proportions in the one stylesheet that loads before
        first paint. A persona that arrived a moment later would be an
        interface visibly correcting itself into the Resident's identity.
        """
        persona = self.active(active)
        if persona is None:
            return ""

        rules = []
        chosen = _legible(persona, scheme)
        for key, colour in chosen.items():
            alpha = persona.alpha(key)
            if alpha is not None and alpha < 1:
                # Mixed in the browser rather than flattened here, so what
                # shows through a bubble is whatever is actually behind it --
                # the persona's own artwork, not an assumption about it.
                colour = (f"color-mix(in srgb, {colour} {alpha * 100:g}%,"
                          " transparent)")
            rules.append(f"  {COLOURS[key]}: {colour};")
        if TEXT in chosen:
            # Restated, not merely redefined. `color` is resolved once where
            # it is declared -- on body, against the root's --text -- and
            # what descends from there is the resulting colour, not the
            # variable. Without this line a persona's text token reaches
            # every rule that mentions var(--text) inside the chat and none
            # of the words themselves, which is exactly the way round that
            # looks like nothing happened.
            rules.append("  color: var(--text);")

        type_rules = []
        if (font := persona.font):
            type_rules.append(f"  font-family: {font};")
        if (size := persona.font_size):
            type_rules.append(f"  font-size: {size};")
        if (weight := persona.font_weight):
            type_rules.append(f"  font-weight: {weight};")

        scrim = ""
        if persona.asset(BACKGROUND) is not None:
            # Served by name rather than inlined: the file may be large, and
            # this stylesheet is on the critical path to first paint.
            rules += [
                "  background-image: "
                f'url("/api/personas/{_quote(persona.name)}/background");',
                "  background-size: cover;",
                "  background-position: center;",
            ]
            # A scrim, emitted with the picture and never without it.
            #
            # A persona may choose the room; it does not get to make the
            # conversation hard to read. Whatever anybody ships, the text on
            # top of it stays legible, and an owner who has no background
            # does not pay a layer of dimming for a picture that is not
            # there.
            scrim = (
                ".chat::before {\n"
                '  content: "";\n'
                "  position: absolute;\n"
                "  inset: 0;\n"
                "  background: var(--bg);\n"
                f"  opacity: {SCRIM};\n"
                "  pointer-events: none;\n"
                "}\n"
            )
        if not rules and not type_rules:
            return ""

        out = ".chat {\n" + "\n".join(rules + type_rules) + "\n}\n" + scrim
        if RESIDENT in chosen:
            # The reply gets an envelope only because this persona asked for
            # one. Bounded like the owner's so a long answer does not become
            # a full-width slab, and left on the text rather than the row so
            # the avatar stays outside it.
            out += (
                ".chat .msg.resident > .body {\n"
                "  background: var(--resident-bubble);\n"
                f"  padding: {BUBBLE};\n"
                f"  border-radius: {BUBBLE_RADIUS};\n"
                "  display: inline-block;\n"
                "  max-width: 80%;\n"
                "}\n"
            )
        if type_rules:
            # Code keeps the interface's type. Inline code sizes itself in
            # `em`, so without this it would ride along with a persona that
            # asked for large text, and a mono stack would inherit a serif.
            out += (
                ".chat .markdown code {\n"
                f"  font-family: {FONTS['mono']};\n"
                f"  font-size: {CODE_FONT_SIZE};\n"
                "  font-weight: 400;\n"
                "}\n"
            )
        return out


def _legible(persona: Persona, scheme: dict[str, str] | None) -> dict[str, str]:
    """A persona's colours, minus any that would make the chat unreadable.

    Each one is dropped on its own rather than the set being refused: a
    persona with one bad value should arrive wearing the rest of its clothes.
    What is dropped falls back to the interface's own token, which is by
    definition readable, because the owner is already reading the interface
    in it.
    """
    chosen = {k: c for k in COLOURS if (c := persona.colour(k))}
    if scheme is None:
        return chosen

    ground = scheme.get("bg", "#000000")
    # Text is checked first: everything after it is checked against whatever
    # text ends up being, the persona's or the interface's.
    if (text := chosen.get(TEXT)) and contrast(text, ground) < MIN_TEXT:
        del chosen[TEXT]
    text = chosen.get(TEXT) or scheme.get("text", "#ffffff")

    if (muted := chosen.get(MUTED)) and contrast(muted, ground) < MIN_MUTED:
        del chosen[MUTED]
    # The bubbles and the composer's box are grounds of their own, and the
    # words on them are the same words. A translucent bubble is checked as
    # what it will look like over the chat's own ground: a persona does not
    # get to pass by making its bubble almost invisible.
    #
    # A bubble that is entirely transparent is left alone. It is not a ground
    # at all -- the words sit on the chat itself, which was checked above.
    for key in (OWNER, RESIDENT, SURFACE):
        surface = chosen.get(key)
        if not surface:
            continue
        alpha = persona.alpha(key)
        if alpha == 0:
            continue
        if alpha is not None and alpha < 1:
            surface = blend(surface, ground, alpha)
        if contrast(text, surface) < MIN_TEXT:
            del chosen[key]
    # Send: whatever the label is drawn in has to survive the button.
    accent = chosen.get(ACCENT) or scheme.get("accent", "#000000")
    if (on := chosen.get(ON_ACCENT)) and contrast(on, accent) < MIN_TEXT:
        del chosen[ON_ACCENT]
    return chosen


def _quote(name: str) -> str:
    """A persona name, safe inside a CSS url().

    A name reaches this from a folder on disk or from frontmatter, and both
    are things a downloaded package controls. Percent-encoding everything
    outside a short safe set means a name cannot close the url(), the
    declaration, or the rule.
    """
    from urllib.parse import quote

    return quote(name, safe="")


def _theme(path: Path, broken: dict[str, str], folder: str) -> dict[str, Any]:
    """theme.json, or nothing, and never an exception.

    A persona with unreadable presentation settings should arrive with its
    writing working and its appearance ignored. The behavioural half is the
    part that matters and it should not be lost to a stray comma.
    """
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        broken[folder] = f"{THEME_FILE} could not be read: {exc}"
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _without_frontmatter(text: str) -> str:
    if not text.startswith(FENCE):
        return text
    end = text.find(f"\n{FENCE}", len(FENCE))
    if end == -1:
        return text
    return text[end + len(FENCE) + 1:]


def _first_line(text: str) -> str:
    """The first line worth showing, skipping headings and blanks."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped[:200]
    return ""


def _frontmatter(text: str) -> dict[str, str]:
    """The frontmatter's scalar fields, if there is any.

    The same shape skills.py parses, and deliberately the same limitation:
    `key: value` on one line, continued across indented lines. Optional here
    where it is required there, because the persona format's own example
    does not use it.
    """
    if not text.startswith(FENCE):
        return {}
    end = text.find(f"\n{FENCE}", len(FENCE))
    if end == -1:
        return {}

    fields: dict[str, str] = {}
    key: str | None = None
    for line in text[len(FENCE):end].splitlines():
        if not line.strip():
            continue
        if line[:1].isspace() and key:
            fields[key] = f"{fields[key]} {line.strip()}".strip()
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        fields[key] = value.strip().strip("'\"")
    return fields
