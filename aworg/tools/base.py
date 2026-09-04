"""What a tool is, and what using one produces.

A tool is described in AWORG's own vocabulary and translated into each
provider's shape inside `models/`. Nothing above that layer knows whether the
model behind it wants `tools[].function.parameters` or `tools[].input_schema`,
and nothing below it knows what a Living Workspace is.

The shape of a result is the more considered half of this file. A tool returns
two things: what the model is told, and what AWORG saw. They are not the same,
and keeping them apart is the whole of the verification argument made concrete.
The model reads `output` and may say anything it likes about it. `observed` is
what actually happened -- the exit code, the duration, the directory it ran in
-- recorded by AWORG, never written by a model, and available to the interface
and to the lifecycle. A Resident claiming a command succeeded can be checked
against the record of it exiting 1.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResult:
    """The outcome of one tool call."""

    #: What the model is shown. Never truncated: a result cut in half is a
    #: result the model reasons about while believing it saw everything.
    output: str

    #: What AWORG observed while it happened. Facts, not testimony.
    observed: dict[str, Any] = field(default_factory=dict)

    #: Whether it did not work. Distinct from an empty output, which is a
    #: perfectly ordinary thing for a successful command to produce.
    failed: bool = False

    def for_model(self) -> str:
        """The result as text, with the facts the model must not miss.

        The exit status is prepended rather than left for the model to infer
        from the output, because inferring it is exactly what a model does
        badly and confidently -- and a command that printed nothing and
        failed looks, from the output alone, like a command that worked.
        """
        head = []
        if "exit_code" in self.observed:
            head.append(f"exit code {self.observed['exit_code']}")
        if self.observed.get("duration_ms") is not None:
            head.append(f"{self.observed['duration_ms']} ms")
        if self.observed.get("truncated_stream"):
            head.append("output stopped early")
        prefix = f"[{', '.join(head)}]\n" if head else ""
        body = self.output if self.output.strip() else "(no output)"
        return prefix + body


class Tool:
    """One thing the Resident can do.

    Subclasses declare a name, a description the model routes on, and a JSON
    Schema for the arguments. The description is not documentation -- it is
    the only thing a model has to decide whether this is the right tool, so
    it is written for that purpose and kept short enough to be read.
    """

    name: str = ""
    description: str = ""
    parameters: dict[str, Any] = {"type": "object", "properties": {}}

    async def run(self, **arguments: Any) -> ToolResult:
        raise NotImplementedError

    def definition(self) -> dict[str, Any]:
        """The tool as AWORG describes it, before any provider sees it."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


class Registry:
    """The tools available, and the means of running one by name.

    Deliberately small. Tool-selection accuracy falls away as the surface
    grows -- measured on the models this is developed against, routing is
    reliable at around five tools and not at fifteen -- so every addition
    here is accuracy spent, and should be worth it.
    """

    def __init__(self, tools: list[Tool] | None = None):
        self._tools: dict[str, Tool] = {}
        for tool in tools or []:
            self.add(tool)

    def add(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def definitions(self) -> list[dict[str, Any]]:
        return [tool.definition() for tool in self._tools.values()]

    async def invoke(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Run a tool by name, turning every failure into a result.

        A model that asks for a tool that does not exist, or passes the wrong
        arguments, has made a mistake it can recover from if it is told. An
        exception here would end the turn instead, so nothing raises: the
        mistake becomes a result the model reads and can correct.
        """
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(
                output=f"There is no tool called {name!r}. Available: "
                       f"{', '.join(self.names()) or 'none'}.",
                observed={"error": "unknown_tool", "requested": name},
                failed=True,
            )

        started = time.monotonic()
        try:
            result = await tool.run(**arguments)
        except TypeError as exc:
            # Almost always the model supplying arguments the tool does not
            # take, which is worth saying precisely.
            return ToolResult(
                output=f"{name} could not be called with those arguments: {exc}",
                observed={"error": "bad_arguments", "tool": name,
                          "arguments": arguments},
                failed=True,
            )
        except Exception as exc:                                  # noqa: BLE001
            return ToolResult(
                output=f"{name} failed: {type(exc).__name__}: {exc}",
                observed={"error": "tool_raised", "tool": name,
                          "exception": type(exc).__name__},
                failed=True,
            )

        result.observed.setdefault("tool", name)
        result.observed.setdefault(
            "duration_ms", int((time.monotonic() - started) * 1000)
        )
        return result
