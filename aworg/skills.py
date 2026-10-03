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

#: Conditions a skill may declare for when it is still worth offering.
#:
#: A getting-started skill is exactly right until the Resident has understood
#: the job, and clutter afterwards. Rather than have AWORG reach in and flip
#: the owner's switch -- which would leave nobody able to tell whether a skill
#: was off because they said so or because something happened -- the skill
#: says when it applies and that is evaluated fresh every turn.
#:
#: The owner's switch is still theirs and still wins. These narrow further;
#: they never re-enable.
#:
#: `plan-is-empty` retires a skill once any task exists. That moment is
#: chosen deliberately over the Lifecycle stage: a stage advances the instant
#: a file appears in the workspace, which says nothing about whether the
#: Resident understood what it was asked. A task existing means it asked
#: enough to form a plan, which is precisely when advice about how to start
#: has done its work.
ACTIVE_WHILE = ("always", "plan-is-empty")

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
        active_while: str = "always",
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
        #: When this skill still applies. See ACTIVE_WHILE.
        self.active_while = active_while
        #: Everything else the frontmatter declared. Carried rather than
        #: discarded so the pane can show it and nothing is silently lost,
        #: and because the spec's own position on fields a runtime does not
        #: act on is to accept them.
        self.extras = extras or {}

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
            "active_while": self.active_while,
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
        has_plan: Any = None,
        shipped_names: set[str] | None = None,
    ):
        #: Which folders in the home AWORG put there. See install.seeded.
        self.shipped_names = shipped_names or set()
        #: Asked per skill name, on every use rather than captured, so the
        #: owner turning one off takes effect on the next message instead of
        #: at the next restart -- the same rule capabilities follow.
        self.is_enabled = is_enabled or (lambda _name: True)
        #: Whether the Resident has written any tasks down. Asked rather
        #: than remembered, for the same reason the switch is: a plan made
        #: this turn should retire a getting-started skill on the next
        #: message, not at the next restart.
        self.has_plan = has_plan or (lambda: False)
        #: The package's own skills/ -- the seed the installer copies into
        #: a home, not a library. Nothing passes it at runtime any more: an
        #: Aworg reads its skills from its home, where the installer put
        #: them. See install.py.
        self.shipped_root = shipped
        #: The owner's, under their Aworg home. This is also where a Resident
        #: writes one it has worked out for itself, which is the whole point
        #: of a skill being a file rather than a setting.
        self.installed_root = installed
        self._skills: dict[str, Skill] = {}
        self.broken: dict[str, str] = {}
        self.discover()

    def discover(self) -> None:
        """Re-read the skills on disk, without ever being half-read.

        Built into locals and swapped in at the end rather than cleared and
        refilled in place. The interface re-reads the library on every
        request for the list, sync endpoints run in a threadpool, and a
        read_skill arriving inside that window would look its name up in a
        dictionary that had just been emptied -- reporting a skill that does
        not exist, and listing the ones that had not been read back in yet as
        the alternatives.

        The identical bug in personas.py was caught in the act: a chat
        background whose stylesheet request 404'd while a manual request a
        moment later succeeded. Nothing had gone looking for it here, which
        is not the same as it not being there.

        A single rebind is atomic, so a reader sees either the old library or
        the new one and never the gap between them.
        """
        found: dict[str, Skill] = {}
        broken: dict[str, str] = {}
        # Shipped first, so an installed skill of the same name replaces it.
        for root, source in ((self.shipped_root, SHIPPED),
                             (self.installed_root, INSTALLED)):
            if root is None or not root.is_dir():
                continue
            for folder in sorted(root.iterdir()):
                if not folder.is_dir() or folder.name.startswith((".", "_")):
                    continue
                manifest = folder / SKILL_FILE
                if not manifest.is_file():
                    broken[folder.name] = f"has no {SKILL_FILE}"
                    continue
                try:
                    meta = _frontmatter(manifest.read_text(encoding="utf-8"))
                except OSError as exc:
                    broken[folder.name] = str(exc)
                    continue

                invocable = not _flag(meta.get("disable-model-invocation"))
                active = (meta.get("active-while") or "always").strip()
                if active not in ACTIVE_WHILE:
                    # An unknown condition is treated as no condition rather
                    # than as false. A typo should not silently hide a skill.
                    active = "always"
                    broken[folder.name] = (
                        f"unknown active-while {meta.get('active-while')!r}; "
                        "offering it unconditionally"
                    )
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
                    broken[folder.name] = "declares no description"
                    continue
                found[name] = Skill(
                    name, description, manifest,
                    SHIPPED if folder.name in self.shipped_names else source,
                    invocable, active,
                    {k: v for k, v in meta.items()
                     if k not in ("name", "description", "when_to_use",
                                  "disable-model-invocation",
                                  "active-while")},
                )

        self._skills, self.broken = found, broken

    def all(self) -> list[Skill]:
        """Every discovered skill, switched on or off.

        The pane needs the lot, because a skill the owner has disabled still
        has to be visible in order to be switched back on.
        """
        return sorted(self._skills.values(), key=lambda s: s.name)

    #: Why a skill is not available to the Resident, in the owner's terms.
    #: Three situations that one "disabled" would flatten into one, and they
    #: call for three different responses: a switch the owner could flip, a
    #: condition that has simply passed, or the skill author's own decision.
    OFF = "switched off by the owner"
    RETIRED = "applies only before there is a plan"
    OWNER_ONLY = "marked for the owner to run deliberately"

    def standing(self, skill: Skill) -> tuple[bool, str]:
        """Whether the Resident may use this skill, and if not, why not.

        The one place the three rules live. `offered` filters on this and
        list_skills explains it, so a fourth reason to hold a skill back --
        or a change to one of these three -- lands in both without either
        having to know about the other. They encoded the same rules
        separately for about an hour and that was already one copy too many.
        """
        if not skill.model_invocable:
            return False, self.OWNER_ONLY
        if not self.is_enabled(skill.name):
            return False, self.OFF
        if not self._still_applies(skill):
            return False, self.RETIRED
        return True, ""

    def offered(self) -> list[Skill]:
        """What the Resident actually gets.

        Three ways to be left out, and they mean different things. The
        owner switched it off, which is theirs to decide; the skill's own
        frontmatter says disable-model-invocation, which is the author
        saying this one is for a person to run deliberately; or the skill
        declared a condition that no longer holds, like advice on starting
        a project once a project has been started.

        Which of the three is `standing`'s business, not this one's. Here
        they are all simply "no".
        """
        return [s for s in self.all() if self.standing(s)[0]]

    def _still_applies(self, skill: Skill) -> bool:
        """Whether a skill's own declared condition is still met."""
        if skill.active_while == "plan-is-empty":
            return not self.has_plan()
        return True

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
        """The offered skills, by name and description, on every message.

        Bodies are never here; read_skill fetches one when it is needed, so a
        dozen skills cost a list rather than a book.
        """
        skills = self.offered()
        if not skills:
            return ""
        listed = "\n".join(f"- {s.name}: {s.description}" for s in skills)
        return (
            "SKILLS\n"
            "Each is a written procedure for one kind of job. Only this "
            "summary is here; call read_skill with the name to load the full "
            "text when you take on that job.\n" + listed
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
