"""Discovering Capabilities and invoking the Tools inside them.

The registry is the only thing that knows a tool is a Python module. Above
it, a tool is a name, a schema, and something you can call -- which is what
lets a native Python tool and a future external MCP tool sit in the same list
and look the same to the Resident.

Discovery reads each tool file's declarations *without importing it*, then
imports on first use. Two reasons. A tool whose dependency is missing should
appear in the Capabilities pane as broken rather than take the Aworg down at
startup, and an Aworg that never touches the browser should not pay to import
what a browser tool needs.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import inspect
import shutil
import sys
import types
from pathlib import Path
from typing import Any, Callable, Iterable

from .base import ToolContext, ToolError, ToolResult, ToolSpec


TOOLS_PACKAGE = "aworg.tools"

#: The name installed capabilities are loaded under. Nothing imports this and
#: no such package exists on disk; it is a namespace so that the modules of an
#: installed capability have a parent to import each other through, and so
#: that they show up in sys.modules under a name that says where they came
#: from rather than colliding with anything real.
INSTALLED_PACKAGE = "aworg_capabilities"

#: Files inside a capability folder that are not tools.
SKIP = {"__init__.py"}


class Capability:
    """A folder of related Tools, installed together and switched together."""

    def __init__(
        self,
        identifier: str,
        label: str,
        description: str,
        path: Path,
        builtin: bool = True,
        internal: bool = False,
        required: bool = False,
    ):
        self.id = identifier
        self.label = label
        self.description = description
        self.path = path
        #: Prepackaged rather than downloaded. It loads by exactly the same
        #: path as anything else -- the flag only says where it came from,
        #: so that the first downloaded capability is not the first thing to
        #: exercise the loader.
        self.builtin = builtin
        #: An environment-embedded Capability: how the Resident reaches an
        #: AWORG subsystem, rather than a package the owner chose to add.
        #: Hidden from the Capabilities pane and not switchable, because the
        #: owner turning it off would be disabling machinery rather than
        #: reach -- the things it exposes are configured elsewhere.
        self.internal = internal
        #: Shown, priced, and not switchable. The third state, and it exists
        #: because two were not enough.
        #:
        #: Filesystem had a switch, and the switch was worse than useless.
        #: Turning it off does not stop a Resident manipulating files -- with
        #: Shell still on it falls back to Get-Content and Set-Content, doing
        #: the same work unnamed and in a shell string. Turn both off and
        #: what is left cannot read, write or run anything: an Aworg that
        #: talks and plans and never touches the machine it lives on.
        #:
        #: So the control offered a choice between working and not working,
        #: dressed as a safety decision. A control that looks meaningful and
        #: is not is worse than no control at all.
        #:
        #: Not internal, though, and the difference matters. Internal means
        #: machinery the owner has no business seeing here; this is reach the
        #: owner should absolutely see, and should see the price of, because
        #: it rides along with every message. They simply should not be
        #: handed a switch that breaks their Aworg.
        #:
        #: Shell and HTTP stay switchable, because those switches mean
        #: something: Shell off is a real posture -- writes files, runs
        #: nothing -- and HTTP off is degraded rather than broken.
        self.required = required
        self.tools: list[ToolSpec] = []
        #: Recorded per tool file that would not parse, so the pane can say
        #: which one and why instead of the tool merely being absent.
        self.broken: dict[str, str] = {}


class Registry:
    """Every Tool this Aworg can offer, and the one way to call them."""

    def __init__(
        self,
        root: Path | None = None,
        installed: Path | None = None,
        is_enabled: Callable[[str], bool] | None = None,
    ):
        self.root = root or Path(__file__).parent
        #: capabilities/ in the Aworg's home: what the owner installed. None
        #: for an Aworg with no home, which is every test that does not need
        #: one.
        self.installed_root = installed
        #: Asked per capability id. Defaults to enabled, so a fresh Aworg
        #: works before anything has been configured.
        self.is_enabled = is_enabled or (lambda _identifier: True)
        self._capabilities: dict[str, Capability] = {}
        #: Installed folders that were not loaded, and why. Kept so the pane
        #: can say so: a capability that is simply absent looks exactly like
        #: one that was never installed, and the owner who just copied it in
        #: deserves the difference.
        self.rejected: dict[str, str] = {}
        #: What each installed capability's files looked like at the last
        #: discovery, so `refresh` can tell which ones changed on disk.
        self._fingerprints: dict[str, tuple] = {}
        self.discover()

    # -- discovery ------------------------------------------------------

    def discover(self) -> None:
        """Read both roots: what AWORG ships, then what the owner installed.

        Built-in first and never overridden. An installed folder named
        `shell` is refused rather than allowed to replace the real one --
        installing a capability is already a decision to run someone's code
        as this Aworg, and it should not additionally be a way to silently
        stand in front of the tools the Resident depends on.
        """
        self._capabilities = {}
        self.rejected = {}
        roots = [(self.root, True)]
        if self.installed_root is not None and self.installed_root.is_dir():
            roots.append((self.installed_root, False))
        for root, builtin in roots:
            for folder in sorted(root.iterdir()):
                if not folder.is_dir() or folder.name.startswith(("_", ".")):
                    continue
                if not builtin and folder.name in self._capabilities:
                    self.rejected[folder.name] = (
                        "not loaded: AWORG has a built-in capability with this "
                        "name, and a built-in is never replaced"
                    )
                    continue
                capability = self._read_capability(folder, builtin=builtin)
                if capability is not None:
                    self._capabilities[capability.id] = capability
                elif not builtin:
                    self.rejected[folder.name] = (
                        "not loaded: no tool files in it. A capability is a "
                        "folder of .py files, each declaring NAME, DESCRIPTION "
                        "and run()"
                    )
        self._fingerprints = self._fingerprint_installed()

    # -- reloading ------------------------------------------------------

    def _fingerprint_installed(self) -> dict[str, tuple]:
        """Every installed capability folder, and the name, size and time of
        each Python file in it.

        Cheap enough to take before every turn: a stat per file, and an
        installed capability is a handful of files. Only .py files count,
        because they are the only thing a reload changes -- a capability
        that writes a cache or a log into its own folder must not reload
        itself by doing so.
        """
        found: dict[str, tuple] = {}
        root = self.installed_root
        if root is None or not root.is_dir():
            return found
        for folder in root.iterdir():
            if not folder.is_dir() or folder.name.startswith(("_", ".")):
                continue
            files: list[tuple] = []
            try:
                _python_files(folder, folder, files)
            except OSError:
                # Mid-copy, most likely. Read as changed; the next look will
                # see it finished.
                files.append(("?", 0, 0))
            found[folder.name] = tuple(sorted(files))
        return found

    async def refresh(self) -> list[str]:
        """Pick up capabilities installed, updated or removed since the last
        look, without a restart. Returns the ids that changed.

        Asked before every turn, so `aworg get` -- or the owner copying a
        folder in -- takes effect on the next message. Only the capabilities
        whose files changed are reloaded: installing Weather must not close
        the page the Browser has open.

        A changed capability's loaded modules are dropped so the next call
        imports the new code, all of it. Keeping some would mix versions: a
        tool already called would run the old file and a tool not yet called
        would run the new one. Before they go, any of them that defines
        `unload()` is given the chance to clean up -- the Browser closes its
        engine there, which would otherwise be orphaned with nobody holding
        its handle.

        A call already running keeps the module it started with; Python does
        not take a module away from code that is using it.
        """
        current = self._fingerprint_installed()
        if current == self._fingerprints:
            return []
        changed = sorted(
            identifier for identifier in set(current) | set(self._fingerprints)
            if current.get(identifier) != self._fingerprints.get(identifier)
        )
        for identifier in changed:
            await _unload_installed(identifier)
            # Python trusts a cached .pyc whose source has the same size and
            # the same modified second -- which a quick edit or an update
            # that changes one character can both produce. Measured: the
            # reload ran the old code. So the cache goes too.
            folder = self.installed_root / identifier if self.installed_root else None
            if folder is not None and folder.is_dir():
                for cache in list(folder.rglob("__pycache__")):
                    shutil.rmtree(cache, ignore_errors=True)
        importlib.invalidate_caches()
        self.discover()
        return changed

    def _read_capability(self, folder: Path, builtin: bool = True) -> Capability | None:
        meta = _module_constants(folder / "__init__.py")
        capability = Capability(
            identifier=folder.name,
            label=meta.get("LABEL") or folder.name.replace("_", " ").title(),
            description=meta.get("DESCRIPTION", ""),
            path=folder,
            builtin=builtin,
            # Only AWORG's own capabilities may declare themselves machinery
            # or undisableable. Both flags remove a control from the owner,
            # and an installed folder that could remove its own switch --
            # or hide from the pane entirely -- would be a capability that
            # installs itself out of sight.
            internal=builtin and bool(meta.get("INTERNAL")),
            required=builtin and bool(meta.get("REQUIRED")),
        )
        for file in sorted(folder.glob("*.py")):
            if file.name in SKIP or file.name.startswith("_"):
                continue
            try:
                declared = _module_constants(file, required=("NAME", "DESCRIPTION"))
            except ValueError as exc:
                capability.broken[file.stem] = str(exc)
                continue
            capability.tools.append(
                ToolSpec(
                    name=declared["NAME"],
                    description=declared["DESCRIPTION"],
                    input_schema=declared.get(
                        "INPUT_SCHEMA", {"type": "object", "properties": {}}
                    ),
                    capability=capability.id,
                    module_name=file.stem,
                    dynamic=bool(declared.get("DYNAMIC")),
                    # Only for the installed ones, which have no import path.
                    path=None if builtin else file,
                )
            )
        return capability if (capability.tools or capability.broken) else None

    # -- reading --------------------------------------------------------

    def capabilities(self) -> list[Capability]:
        return list(self._capabilities.values())

    def get_capability(self, identifier: str) -> Capability | None:
        return self._capabilities.get(identifier)

    def specs(self, scope: Iterable[str] | None = None) -> list[ToolSpec]:
        """The tools a given caller may use.

        `scope` is a set of tool names, capability ids, or both -- which is
        how a worker is handed three tools where the Resident has all of
        them. None means everything enabled, which is the Resident today.

        A disabled capability is invisible even when named in a scope. The
        owner's switch outranks whatever the Resident asked a worker to
        carry, because it is the owner's machine.

        Nothing here knows or cares what operating system this is. Tools are
        OS-dependent and it is the tool's business to be: one that cannot run
        here says so when it is called, in its own words, which are better
        words than anything this file could invent. A filter here would be
        AWORG translating between environments, and that layer is exactly
        what must not exist -- it would be wrong everywhere at once and it
        would grow forever.
        """
        wanted = set(scope) if scope is not None else None
        chosen: list[ToolSpec] = []
        for capability in self._capabilities.values():
            # Internal capabilities have no switch, so they are never asked
            # about -- there is nowhere in the interface to have turned one
            # off, and treating an absent answer as "disabled" would make
            # delegation vanish silently.
            # Required ones are never asked about either. There is no
            # switch to have turned off, and an absent answer read as
            # "disabled" would take the filesystem away silently.
            if (
                not capability.internal
                and not capability.required
                and not self.is_enabled(capability.id)
            ):
                continue
            for spec in capability.tools:
                if wanted is None or spec.name in wanted or capability.id in wanted:
                    chosen.append(spec)
        return chosen

    def descriptors(
        self, scope: Iterable[str] | None = None, **live: Any
    ) -> list[dict[str, Any]]:
        """The tool list as MCP describes it, ready for an adapter.

        Most tools describe themselves once, at discovery, from constants in
        their own file. A tool marked DYNAMIC describes itself here instead,
        from whatever `live` state it is given -- spawn_worker does, because
        its enumeration is the owner's connections and those change without
        any code changing.

        A dynamic tool that returns nothing is left out entirely: with no
        usable connection there is no spawn_worker.
        """
        out: list[dict[str, Any]] = []
        for spec in self.specs(scope):
            if not spec.dynamic:
                out.append(spec.descriptor())
                continue
            try:
                described = self._load(spec).describe_for(**live)
            except Exception:                                 # noqa: BLE001
                # A broken dynamic descriptor should cost that one tool, not
                # every tool and the turn along with them.
                continue
            if described:
                out.append(described)
        return out

    def find(self, name: str, scope: Iterable[str] | None = None) -> ToolSpec | None:
        for spec in self.specs(scope):
            if spec.name == name:
                return spec
        return None

    # -- invoking -------------------------------------------------------

    def _load(self, spec: ToolSpec) -> Any:
        if spec.module is None:
            if spec.path is None:
                spec.module = importlib.import_module(
                    f"{TOOLS_PACKAGE}.{spec.capability}.{spec.module_name}"
                )
            else:
                spec.module = _load_installed(spec)
        return spec.module

    async def invoke(
        self,
        name: str,
        arguments: dict[str, Any],
        context: ToolContext,
        scope: Iterable[str] | None = None,
    ) -> ToolResult:
        """Run one tool and return its result.

        Every failure short of a bug in AWORG comes back as a result with
        `is_error` set rather than as an exception. The model can act on
        being told the file was not there; it cannot act on a traceback, and
        a loop that breaks on the first bad argument is a loop that gives up
        the moment a small model guesses a parameter name wrong.
        """
        spec = self.find(name, scope)
        if spec is None:
            offered = ", ".join(s.name for s in self.specs(scope)) or "none"
            return ToolResult(
                text=(
                    f"There is no tool called {name!r} available to you. "
                    f"Available tools: {offered}."
                ),
                is_error=True,
                summary="unknown tool",
            )

        try:
            module = self._load(spec)
        except Exception as exc:                              # noqa: BLE001
            return ToolResult(
                text=f"The tool {name!r} could not be loaded: {exc}",
                is_error=True,
                summary="failed to load",
            )

        try:
            result = module.run(context, **arguments)
            if inspect.isawaitable(result):
                result = await result
        except ToolError as exc:
            return ToolResult(text=str(exc), is_error=True, summary="failed")
        except TypeError as exc:
            # Almost always the model inventing or omitting a parameter.
            # Naming the schema back at it is what lets the next attempt be
            # right, which matters most on exactly the small models this is
            # built for.
            expected = ", ".join(spec.input_schema.get("properties", {})) or "none"
            return ToolResult(
                text=(
                    f"{name} was called with arguments it does not accept: {exc}. "
                    f"It accepts: {expected}."
                ),
                is_error=True,
                summary="bad arguments",
            )
        except Exception as exc:                              # noqa: BLE001
            return ToolResult(
                text=f"{name} failed unexpectedly: {exc.__class__.__name__}: {exc}",
                is_error=True,
                summary="failed",
            )

        if not isinstance(result, ToolResult):
            # A tool that returns a bare string is doing the common thing;
            # accepting it costs nothing and keeps simple tools simple.
            result = ToolResult(text=str(result))
        return result


def _python_files(folder: Path, top: Path, into: list[tuple]) -> None:
    """The .py files in a capability, for its fingerprint: the top level,
    and any subfolder that is a Python package. Not every subfolder -- the
    Browser keeps a whole Chromium in its own, and walking thousands of
    engine files every few seconds to find no Python in them is waste."""
    for entry in folder.iterdir():
        if entry.is_file() and entry.suffix == ".py":
            stat = entry.stat()
            into.append((entry.relative_to(top).as_posix(), stat.st_size, stat.st_mtime_ns))
        elif (entry.is_dir() and entry.name != "__pycache__"
              and (entry / "__init__.py").is_file()):
            _python_files(entry, top, into)


async def _unload_installed(identifier: str) -> None:
    """Drop every loaded module of one installed capability, after letting
    each that defines `unload()` clean up. A failing unload costs that
    cleanup, never the reload."""
    package = f"{INSTALLED_PACKAGE}.{identifier}"
    names = [name for name in list(sys.modules)
             if name == package or name.startswith(package + ".")]
    for name in names:
        hook = getattr(sys.modules.get(name), "unload", None)
        if callable(hook):
            try:
                result = hook()
                if inspect.isawaitable(result):
                    await result
            except Exception:                                 # noqa: BLE001
                pass
    for name in names:
        sys.modules.pop(name, None)


def _load_installed(spec: ToolSpec) -> Any:
    """Import one tool file that lives outside the package.

    The same import machinery Python uses for everything else, pointed at a
    path instead of at a package -- and the module is put in sys.modules under
    a parent that carries the capability folder as its search path, so that a
    capability made of several files can say `from ._shared import ...` like
    any other Python. It runs in this process with everything AWORG has,
    which is the bargain of installing it.
    """
    package = f"{INSTALLED_PACKAGE}.{spec.capability}"
    name = f"{package}.{spec.module_name}"
    if name in sys.modules:
        return sys.modules[name]

    if INSTALLED_PACKAGE not in sys.modules:
        root = types.ModuleType(INSTALLED_PACKAGE)
        root.__path__ = []                    # a package with no directory
        sys.modules[INSTALLED_PACKAGE] = root
    if package not in sys.modules:
        parent = types.ModuleType(package)
        parent.__path__ = [str(Path(spec.path).parent)]
        sys.modules[package] = parent

    module_spec = importlib.util.spec_from_file_location(name, spec.path)
    if module_spec is None or module_spec.loader is None:
        raise ImportError(f"{spec.path} could not be read as a Python module")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    try:
        module_spec.loader.exec_module(module)
    except BaseException:
        # A half-imported module left in sys.modules would be handed out on
        # the next call as though it had worked.
        sys.modules.pop(name, None)
        raise
    return module


def _module_constants(
    path: Path, required: tuple[str, ...] = ()
) -> dict[str, Any]:
    """Read a module's top-level literal assignments without importing it.

    Parsing rather than importing is what makes lazy loading possible while
    still knowing every tool's name and schema at startup. It also means a
    tool file with a syntax error or a missing dependency is reported as one
    broken tool rather than preventing the Aworg from starting.
    """
    if not path.exists():
        return {}
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        raise ValueError(f"could not be parsed: {exc.msg} (line {exc.lineno})") from exc

    found: dict[str, Any] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                try:
                    found[target.id] = ast.literal_eval(node.value)
                except ValueError:
                    # A computed constant. Not something a declaration
                    # should be, and not worth failing the whole file over.
                    continue

    missing = [name for name in required if name not in found]
    if missing:
        raise ValueError(f"does not declare {', '.join(missing)}")
    return found
