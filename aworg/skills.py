"""Skills: knowing how to do something well, kept so it can be reused.

The third of the three words AWORG keeps apart. A Tool is a thing the Resident
can call; a Capability is a folder of related Tools; a Skill is *procedure* --
how to go about a kind of job using the tools you already have. A skill adds
no new ability. It adds knowing what to do.

The format is the Agent Skills convention rather than anything invented here:
a folder, a SKILL.md with YAML frontmatter naming it and saying when to use
it, and optional references/ alongside for the detail. Following the standard
means a skill written for anything else works here, and one written here works
elsewhere -- which is the same argument that made MCP the tool contract.

The economics matter and are the reason the format is shaped this way. Every
skill's *description* is in the system prompt on every message, because that
is what lets the Resident know a skill exists at the moment it would help.
The *body* is not, and is read only when the Resident asks for it. A dozen
skills therefore cost a paragraph, not a book -- and a skill whose description
does not say when to use it is a skill that will never be reached for, however
good its contents.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


SKILL_FILE = "SKILL.md"

#: Where skills come from, in the order they are searched. A skill in the
#: owner's home wins over a shipped one of the same name, so an owner can
#: replace what AWORG provides without editing anything inside the package.
SHIPPED = "shipped"
INSTALLED = "installed"

#: The spec's cap on description plus when_to_use in a skill listing. Held
#: to because the listing is the thing every message carries, and a skill
#: that quietly ate a thousand tokens of prompt would be a skill nobody
#: could see was expensive.
MAX_DESCRIPTION_CHARS = 1536

#: How much of a skill body to hand over at once. Generous, because a skill
#: is read deliberately rather than stumbled into, and a procedure cut in
#: half is worse than no procedure -- but not unbounded, because a skill is
#: a file on disk and files can be any size.
MAX_BODY_CHARS = 20000


class Skill:
    """One skill: what it is called, when to use it, and how."""

    def __init__(
        self,
        name: str,
        description: str,
        path: Path,
        source: str,
        model_invocable: bool = True,
        extras: dict[str, str] | None = None,
    ):
        self.name = name
        self.description = description
        self.path = path
        self.source = source
        #: `disable-model-invocation` inverted. A skill the author marked
        #: that way is not offered to the Resident at all -- it exists for
        #: the owner to run deliberately, which is the spec's meaning.
        self.model_invocable = model_invocable
        #: Everything else the frontmatter declared. Carried rather than
        #: discarded so the pane can show it and nothing is silently lost,
        #: and because the spec's own position on fields a runtime does not
        #: act on is to accept them.

    @property
    def directory(self) -> Path:
        return self.path.parent

    def body(self) -> str:
        """The procedure itself, without the frontmatter.

        Read from disk each time rather than cached at discovery. A skill the
        Resident is editing should take effect on the next read, and skills
        are small enough that the read costs nothing worth optimising.
        """
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            return f"(this skill could not be read: {exc})"
        return _strip_frontmatter(text).strip()

    def references(self) -> list[str]:
        """Files the skill can point the Resident at for more detail.

        Listed rather than inlined. The whole point of the convention is that
        a skill stays short enough to read and says where the depth is.
        """
        folder = self.directory / "references"
        if not folder.is_dir():
            return []
        return sorted(
            str(p.relative_to(self.directory)).replace("\\", "/")
            for p in folder.rglob("*")
            if p.is_file()
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "source": self.source,
            "model_invocable": self.model_invocable,
            "extras": self.extras,
            "path": str(self.path),
            "references": self.references(),
        }


class SkillLibrary:
    """Every skill this Aworg can reach, from wherever they live."""

    def __init__(
        self,
        shipped: Path | None = None,
        installed: Path | None = None,
        is_enabled: Any = None,
    ):
        #: Asked per skill name, on every use rather than captured, so the
        #: owner turning one off takes effect on the next message instead of
        #: at the next restart -- the same rule capabilities follow.
        self.is_enabled = is_enabled or (lambda _name: True)
        #: Ships inside the package, beside the tools.
        self.shipped_root = shipped or (Path(__file__).parent / "skills")
        #: The owner's, under their Aworg home. This is also where a Resident
        #: writes one it has worked out for itself, which is the whole point
        #: of a skill being a file rather than a setting.
        self.installed_root = installed
        self._skills: dict[str, Skill] = {}
        self.broken: dict[str, str] = {}
        self.discover()

    def discover(self) -> None:
        self._skills = {}
        self.broken = {}
        # Shipped first, so an installed skill of the same name replaces it.
        for root, source in ((self.shipped_root, SHIPPED),
                             (self.installed_root, INSTALLED)):
            if root is None or not root.is_dir():
                continue
            for folder in sorted(root.iterdir()):
                if not folder.is_dir() or folder.name.startswith((".", "_")):
                    continue
                found = folder / SKILL_FILE
                if not found.is_file():
                    self.broken[folder.name] = f"has no {SKILL_FILE}"
                    continue
                try:
                    meta = _frontmatter(found.read_text(encoding="utf-8"))
                except OSError as exc:
                    self.broken[folder.name] = str(exc)
                    continue

                invocable = not _flag(meta.get("disable-model-invocation"))
                name = (meta.get("name") or folder.name).strip()

                # when_to_use is appended to the description, which is what
                # the spec says it is for: extra trigger detail that counts
                # against the same cap.
                description = (meta.get("description") or "").strip()
                when = (meta.get("when_to_use") or "").strip()
                if when:
                    description = f"{description} {when}".strip()
                if len(description) > MAX_DESCRIPTION_CHARS:
                    # Room for the ellipsis inside the cap, not beyond it.
                    # Truncating to the limit and then appending three
                    # characters puts the result over a limit the whole
                    # point of which is not being exceeded.
                    keep = MAX_DESCRIPTION_CHARS - 3
                    description = description[:keep].rstrip() + "..."
                if not description:
                    # Named rather than silently skipped. A skill with no
                    # description is invisible to the Resident, which looks
                    # exactly like the skill not being installed.
                    self.broken[folder.name] = "declares no description"
                    continue
                self._skills[name] = Skill(
                    name, description, found, source, invocable,
                    {k: v for k, v in meta.items()
                     if k not in ("name", "description", "when_to_use",
                                  "disable-model-invocation")},
                )

    def all(self) -> list[Skill]:
        """Every discovered skill, switched on or off.

        The pane needs the lot, because a skill the owner has disabled still
        has to be visible in order to be switched back on.
        """
        return sorted(self._skills.values(), key=lambda s: s.name)

    def offered(self) -> list[Skill]:
        """What the Resident actually gets.

        Two ways to be left out, and they mean different things. The owner
        switched it off, which is theirs to decide; or the skill's own
        frontmatter says disable-model-invocation, which is the author
        saying this one is for a person to run deliberately.
        """
        return [
            s for s in self.all()
            if s.model_invocable and self.is_enabled(s.name)
        ]

    def get(self, name: str) -> Skill | None:
        """Find a skill the way the Resident names one, forgivingly.

        Matched case-insensitively and ignoring separators, because the name
        travels through a model and comes back with whatever capitalisation
        and hyphenation it felt like.
        """
        wanted = _normalise(name)
        for skill in self.offered():
            if _normalise(skill.name) == wanted:
                return skill
        return None

    def get_any(self, name: str) -> Skill | None:
        """Find a skill whether or not it is switched on.

        `get` deliberately only sees what is offered, so the Resident cannot
        read a disabled skill. Turning one back on needs to find it anyway.
        """
        wanted = _normalise(name)
        for skill in self._skills.values():
            if _normalise(skill.name) == wanted:
                return skill
        return None

    def prompt_block(self) -> str:
        """The skills, as the Resident is told about them every message.

        Names and descriptions only -- the cheap half, present so the
        Resident knows what exists. Bodies are read on demand with
        read_skill. That is the whole point of the convention and it is
        followed exactly: a dozen skills cost a paragraph, not a book.

        There was briefly an `always` field here that carried a skill's whole
        body in the prompt, added because the 9B this is developed against
        never calls read_skill -- one time in eighteen runs, across three
        rewritten descriptions and with the instruction moved into the
        standing prompt. It worked, and it was the wrong fix: a measurement
        about a model became a permanent feature of the format.

        The floor these models represent is meant to prove the loop holds,
        not to be designed around. A model that will not consult a procedure
        it has been told about is a model that cannot be trusted with an
        Aworg's conventions, and the answer to that is a better model rather
        than a bigger prompt.
        """
        skills = self.offered()
        if not skills:
            return ""

        listed = "\n".join(f"  {s.name}: {s.description}" for s in skills)
        return (
            "SKILLS you can load. Call read_skill with the name when the job "
            "matches one of these, before planning or acting -- a skill is "
            "how this machine does that job, which is not always how you "
            f"would.\n" + listed
        )


def _flag(value: Any) -> bool:
    """A frontmatter boolean, in every spelling the spec allows."""
    return str(value or "").strip().lower() in ("true", "yes", "on", "1")


def _normalise(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


#: Opening and closing fence of a YAML frontmatter block.
FENCE = "---"


def _frontmatter(text: str) -> dict[str, str]:
    """The frontmatter's scalar fields, without a YAML library.

    Deliberately not a YAML parser. AWORG has three dependencies and adding
    one to read two scalars would be the same poor trade host.py already
    refused for "how much memory is there".

    What it handles is what the convention actually uses: `key: value` on one
    line, and a value continued across following indented lines, which is how
    a long description gets wrapped. Anything more elaborate is not something
    a SKILL.md should contain.
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
            # A wrapped continuation of the value above.
            fields[key] = f"{fields[key]} {line.strip()}".strip()
            continue
        head, sep, tail = line.partition(":")
        if not sep:
            continue
        key = head.strip()
        fields[key] = tail.strip().strip('"').strip("'")
    return fields


def _strip_frontmatter(text: str) -> str:
    if not text.startswith(FENCE):
        return text
    end = text.find(f"\n{FENCE}", len(FENCE))
    if end == -1:
        return text
    return text[end + len(FENCE) + 1:]
