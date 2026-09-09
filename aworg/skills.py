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
        always: bool = False,
    ):
        self.name = name
        self.description = description
        self.path = path
        self.source = source
        #: Carried in full in every system prompt rather than waiting to be
        #: read. See SkillLibrary.prompt_block for why this exists and when
        #: it is the wrong choice.
        self.always = always

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
            "always": self.always,
            "path": str(self.path),
            "references": self.references(),
        }


class SkillLibrary:
    """Every skill this Aworg can reach, from wherever they live."""

    def __init__(self, shipped: Path | None = None, installed: Path | None = None):
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

                always = str(meta.get("always", "")).strip().lower() in (
                    "true", "yes", "1"
                )
                name = (meta.get("name") or folder.name).strip()
                description = (meta.get("description") or "").strip()
                if not description:
                    # Named rather than silently skipped. A skill with no
                    # description is invisible to the Resident, which looks
                    # exactly like the skill not being installed.
                    self.broken[folder.name] = "declares no description"
                    continue
                self._skills[name] = Skill(name, description, found, source, always)

    def all(self) -> list[Skill]:
        return sorted(self._skills.values(), key=lambda s: s.name)

    def get(self, name: str) -> Skill | None:
        """Find a skill the way the Resident names one, forgivingly.

        Matched case-insensitively and ignoring separators, because the name
        travels through a model and comes back with whatever capitalisation
        and hyphenation it felt like.
        """
        wanted = _normalise(name)
        for skill in self._skills.values():
            if _normalise(skill.name) == wanted:
                return skill
        return None

    def prompt_block(self) -> str:
        """The skills, as the Resident is told about them every message.

        Descriptions for most -- the cheap half, present so the Resident
        knows what exists -- and the full body for any skill marked
        `always: true`.

        That second kind exists because of something measured rather than
        assumed. Given a skill whose description read "use before creating
        any new file, of any kind", and asked to write a file, a 9B wrote the
        file its own way and never called read_skill: wrong folder, wrong
        naming, missing the header the skill requires. Told explicitly to
        read it first, it followed all three conventions exactly.

        So the machinery was right and the disposition was not. A model does
        not consult a reference it does not feel it needs, and it cannot tell
        from the inside that this machine's conventions differ from the ones
        in its training. Progressive disclosure assumes a curiosity that
        smaller models do not have.

        `always` is the escape hatch, and it is deliberately not the default.
        It costs its whole length on every message, so it suits short
        standing rules -- house conventions, hard-won local facts -- and not
        long procedures, which is why web-project does not use it and
        house-style does. The field is additive: any other implementation of
        this format ignores it and the skill still works there.
        """
        skills = self.all()
        if not skills:
            return ""

        standing = [s for s in skills if s.always]
        lines = "\n".join(f"  {s.name}: {s.description}" for s in skills)
        if standing:
            bodies = "\n\n".join(
                f"### {s.name}\n{s.body()}" for s in standing
            )
            lines += (
                "\n\nThese apply to everything you do here, so they are given "
                "in full rather than waiting to be asked for:\n\n" + bodies
            )
        # Written as an instruction rather than a listing, because a listing
        # is what it was and the Resident read straight past it: given a
        # skill about building websites and asked to build a website, it
        # built the website without ever opening the skill.
        #
        # The last sentence is the load-bearing one. A model asked to do
        # something familiar feels no need to consult anything, and cannot
        # tell from the inside that this Aworg's way differs from the one in
        # its training. Saying so is what makes the difference legible.
        return (
            "SKILLS -- procedures this Aworg knows. When a job matches one "
            "of these, call read_skill FIRST, before planning or acting.\n"
            + lines
            + "\nA skill holds what you do not already know: this machine's "
            "conventions, what has gone wrong here before, how this owner "
            "wants it done. Doing such a job your usual way instead is how "
            "you get it confidently and subtly wrong."
        )


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
