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
import inspect
from pathlib import Path
from typing import Any, Callable, Iterable

from .base import ToolContext, ToolError, ToolResult, ToolSpec


TOOLS_PACKAGE = "aworg.tools"

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
        self.tools: list[ToolSpec] = []
        #: Recorded per tool file that would not parse, so the pane can say
        #: which one and why instead of the tool merely being absent.
        self.broken: dict[str, str] = {}


class Registry:
    """Every Tool this Aworg can offer, and the one way to call them."""

    def __init__(
        self,
        root: Path | None = None,
        is_enabled: Callable[[str], bool] | None = None,
    ):
        self.root = root or Path(__file__).parent
        #: Asked per capability id. Defaults to enabled, so a fresh Aworg
        #: works before anything has been configured.
        self.is_enabled = is_enabled or (lambda _identifier: True)
        self._capabilities: dict[str, Capability] = {}
        self.discover()

    # -- discovery ------------------------------------------------------

    def discover(self) -> None:
        self._capabilities = {}
        for folder in sorted(self.root.iterdir()):
            if not folder.is_dir() or folder.name.startswith(("_", ".")):
                continue
            capability = self._read_capability(folder)
            if capability is not None:
                self._capabilities[capability.id] = capability

    def _read_capability(self, folder: Path) -> Capability | None:
        meta = _module_constants(folder / "__init__.py")
        capability = Capability(
            identifier=folder.name,
            label=meta.get("LABEL") or folder.name.replace("_", " ").title(),
            description=meta.get("DESCRIPTION", ""),
            path=folder,
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
        """
        wanted = set(scope) if scope is not None else None
        chosen: list[ToolSpec] = []
        for capability in self._capabilities.values():
            if not self.is_enabled(capability.id):
                continue
            for spec in capability.tools:
                if wanted is None or spec.name in wanted or capability.id in wanted:
                    chosen.append(spec)
        return chosen

    def descriptors(self, scope: Iterable[str] | None = None) -> list[dict[str, Any]]:
        """The tool list as MCP describes it, ready for an adapter."""
        return [spec.descriptor() for spec in self.specs(scope)]

    def find(self, name: str, scope: Iterable[str] | None = None) -> ToolSpec | None:
        for spec in self.specs(scope):
            if spec.name == name:
                return spec
        return None

    # -- invoking -------------------------------------------------------

    def _load(self, spec: ToolSpec) -> Any:
        if spec.module is None:
            spec.module = importlib.import_module(
                f"{TOOLS_PACKAGE}.{spec.capability}.{spec.module_name}"
            )
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
