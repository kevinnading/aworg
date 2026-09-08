"""What a Tool is, and what it is given to work with.

Three words that are easy to blur, kept distinct here and everywhere above:

    Tool          one callable function the model can ask for
    Capability    an installable folder of related Tools
    Skill         knowing how to do something with the Tools you have

A Tool module is a plain Python file declaring four things -- a name, a
description, an MCP input schema, and a `run` -- so that adding one is
writing a file rather than registering anything.

The schema is MCP's, not AWORG's. Where MCP defines how a tool is described,
called, and answered, that is the format used, because a competing tool-call
dialect would buy nothing and cost every future external tool an adapter.
What MCP does not define is how a Python tool is packaged, discovered or run,
and that part is AWORG's own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

from ..activities import Activity, ActivityManager


#: How much of a result the model is shown. A tool that returns a 40,000-line
#: build log would otherwise spend a small model's entire context on one call
#: and leave no room to act on it.
#:
#: Deliberately modest, because this is developed against a 9B whose window
#: may be 8k: 4,000 characters is roughly 1,100 tokens. Generous limits are a
#: setting for whoever runs something larger, not the default.
MAX_RESULT_CHARS = 4000

#: Of what is kept, how much comes from the start. The beginning of output
#: says what ran and the end says how it went, and the middle is usually the
#: repetitive part -- so both edges are kept and the middle is what goes.
HEAD_SHARE = 0.65


class ToolError(Exception):
    """A tool could not do what was asked, in a way worth telling the model.

    Raised for the ordinary failures -- a missing file, a bad argument, a
    command that would not run. The message goes back as the tool's result
    with an error flag rather than breaking the loop, because a model that
    is told what went wrong can try something else, and one that gets an
    exception cannot.
    """


@dataclass
class ToolResult:
    """What came back, in the two forms it is needed in.

    `text` is what the model is shown and what the conversation stores,
    already sized. `payload` is the whole thing, kept on the Activity as
    evidence for an owner who wants to look.

    They are separate because the conversation records what was *said*. If
    the model was handed a truncated log, then the truncated log is what it
    saw, and storing the full one would let a replay reconstruct a
    conversation that never happened.
    """

    text: str
    payload: Any = None
    is_error: bool = False
    #: One short line for the Activities panel: "3 files", "exit 0".
    summary: str = ""


@dataclass
class ToolContext:
    """Everything a tool is allowed to reach for.

    Passed in rather than imported, so a tool has no way to acquire
    something that was not handed to it, and so a test can hand it
    somewhere else to write.
    """

    paths: Any
    activities: ActivityManager
    #: What was observed about this machine, already gathered and kept fresh
    #: by whoever is running the loop. Passed in rather than re-surveyed:
    #: observing costs about two-thirds of a second, which is nothing once at
    #: startup and absurd on every command.
    host: dict[str, Any] = field(default_factory=dict)
    #: The Activity representing this call, so a long-running tool can say
    #: how far it has got without knowing who is listening.
    activity: Activity | None = None
    #: Who is calling: "resident", or a worker id. Tools do not currently
    #: branch on it; it is here so that an audit of who ran what is possible
    #: without changing every signature later.
    source: str = "resident"

    def progress(self, fraction: float | None = None, detail: str = "") -> None:
        if self.activity is not None:
            self.activities.progress(self.activity, fraction, detail)


class ToolModule(Protocol):
    """The shape every tool file has. Not enforced, but relied upon."""

    NAME: str
    DESCRIPTION: str
    INPUT_SCHEMA: dict[str, Any]

    run: Callable[..., Awaitable[ToolResult]]


@dataclass
class ToolSpec:
    """A discovered tool, described the way the model will be told about it."""

    name: str
    description: str
    input_schema: dict[str, Any]
    capability: str
    #: The file it lives in, without the extension. Kept apart from `name`
    #: because a tool is free to call itself something other than its
    #: filename, and resolving the import from the declared name would work
    #: right up until one did.
    module_name: str = ""
    #: Filled on first use. Discovery reads the file's declarations without
    #: importing its dependencies, so an Aworg with a broken tool still
    #: starts and still says which tool is broken.
    module: Any = field(default=None, repr=False)

    def descriptor(self) -> dict[str, Any]:
        """This tool as MCP describes tools."""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


def resolve_path(context: ToolContext, path: str) -> "Path":
    """Turn whatever the model typed into an absolute path.

    A bare or relative path lands in the Living Workspace, because that is
    where the Resident builds by convention and it is what a model means by
    `notes.md` when it has not thought about directories.

    An absolute path is honoured as given. The workspace is a suggestion
    rather than a fence -- see docs/06_ARCHITECTURE.md -- and a Resident
    asked to fix a config file in /etc has been asked to work outside the
    workspace on purpose.
    """
    from pathlib import Path

    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path(context.paths.workspace) / candidate
    return candidate


def size_for_model(text: str, limit: int = MAX_RESULT_CHARS) -> str:
    """Cut a result down to what a model can afford to read.

    The cut is announced in the text itself. A result silently halved
    produces a Resident reasoning confidently about output it never saw,
    which is worse than one that can see it was given an extract and narrow
    its next call.

    Deterministic on purpose. A model-written summary of a tool result is
    testimony about evidence the same model is about to be judged on, and
    costs a round trip to obtain.
    """
    if len(text) <= limit:
        return text

    marker_room = 80
    keep = limit - marker_room
    head_chars = int(keep * HEAD_SHARE)
    tail_chars = keep - head_chars

    head = text[:head_chars]
    tail = text[-tail_chars:] if tail_chars > 0 else ""
    omitted = len(text) - head_chars - tail_chars

    return (
        f"{head}\n\n"
        f"[... {omitted:,} characters omitted by AWORG. "
        f"This is an extract, not the whole result. ...]\n\n"
        f"{tail}"
    )
