"""Spawning a worker, and reporting what it actually did.

A worker is three things and not two:

    connection      which model it thinks with
    system prompt   how it works
    tool scope      what it is allowed to do

The third does the most work and is the easiest to leave out. A checker that
cannot write files cannot damage the workspace however badly it misreads its
job -- it is not trusted to avoid writing, it is simply not handed the means.
It is also what makes a 2B usable as a specialist: three tools and a narrow
prompt are far more reliable than twelve tools and a general prompt.

Workers are temporary. One bounded job, no memory of it afterwards, disposed.
Their conversation is a scratch list that is thrown away when they finish --
which is why the loop takes a `record` callback rather than a store.

The part that matters most is what comes back. A worker's result carries both
what the worker *claimed* and what AWORG *observed* while it worked, because a
worker reporting success on work that failed is precisely the failure the
owner cannot catch for themselves, and it is not fixed by choosing a better
model. It is fixed by the result being evidence rather than testimony.
"""

from __future__ import annotations

from typing import Any

from .activities import ActivityManager
from .agent import AgentLoop
from .models import Message, ModelError, build_adapter
from .secrets import credential_ref
from .tools import Registry, ToolContext


#: A worker gets fewer rounds than the Resident. It has one bounded job and a
#: small model; a 2B still going round eight times has lost the thread rather
#: than closed in on something, and the Resident is waiting on it.
WORKER_MAX_ROUNDS = 6


class WorkerResult:
    """What a worker did, in both of the forms the Resident needs.

    `claimed` is the worker's own account. `observed` is what AWORG watched
    happen -- which tools ran, what they returned, what failed. The Resident
    is shown both and told which is which, so that "it says it worked" and
    "it worked" stay separable.
    """

    def __init__(self, worker: str, task: str):
        self.worker = worker
        self.task = task
        self.claimed: str = ""
        self.calls: list[dict[str, Any]] = []
        self.error: str | None = None

    @property
    def failed_calls(self) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["is_error"]]

    def render(self) -> str:
        """The result as the Resident reads it.

        Deliberately laid out so the evidence cannot be skimmed past. The
        worker's account comes first because it is what was asked for, and
        the observed record follows under a heading that says plainly it is
        AWORG's and not the worker's.
        """
        parts = [f"Worker `{self.worker}` finished."]

        if self.error:
            parts.append(f"\nIt did not complete: {self.error}")

        parts.append(f"\nWhat it reported:\n{self.claimed.strip() or '(it said nothing)'}")

        if not self.calls:
            parts.append(
                "\nWhat AWORG observed: it used no tools at all. Whatever it "
                "reported above, it did not do anything."
            )
        else:
            lines = [
                f"  {'FAILED' if c['is_error'] else 'ok'}  {c['name']}"
                f"({c['arguments']}) -> {c['summary'] or 'no summary'}"
                for c in self.calls
            ]
            parts.append(
                "\nWhat AWORG observed it actually do "
                f"({len(self.calls)} tool call{'s' if len(self.calls) != 1 else ''}"
                + (f", {len(self.failed_calls)} failed" if self.failed_calls else "")
                + "):\n" + "\n".join(lines)
            )

        if self.failed_calls and "fail" not in self.claimed.lower():
            # The exact case this whole design exists for: a worker that
            # reports success over work that did not succeed. The Resident is
            # told, rather than being left to notice.
            parts.append(
                "\nNote: some of those calls failed and the worker's report "
                "does not mention it. Check before relying on this."
            )

        return "\n".join(parts)


async def run_worker(
    worker: dict[str, Any],
    task: str,
    *,
    store: Any,
    secrets: Any,
    registry: Registry,
    activities: ActivityManager,
    paths: Any,
    host_facts: dict[str, Any],
    parent_id: str | None = None,
) -> WorkerResult:
    """Run one worker on one task and come back with what happened.

    The Resident does not call this directly -- it asks for the `delegate`
    tool, which calls this. Everything the worker needs is passed in, so
    nothing here reaches for the Resident's conversation or its connection.
    """
    result = WorkerResult(worker["name"], task)

    connection = _connection_for(worker, store)
    if connection is None:
        result.error = (
            "No model is connected for workers. Set a worker connection in "
            "Settings, or give this worker a connection of its own."
        )
        return result

    api_key = secrets.get(credential_ref(connection["id"]))
    if not api_key:
        result.error = f"{connection['name']} has no credential stored."
        return result

    activity = activities.create(
        kind="worker",
        label=worker["name"],
        source="resident",
        parent_id=parent_id,
        detail=task[:80],
    )
    activities.started(activity)

    loop = AgentLoop(
        adapter=build_adapter(connection, api_key),
        registry=registry,
        context=ToolContext(
            paths=paths, activities=activities, host=host_facts
        ),
        activities=activities,
        # The whole point. An empty scope would mean every enabled tool,
        # which is the Resident's scope and not a worker's, so a worker
        # configured with no tools is given none rather than all.
        scope=list(worker.get("tools") or []),
        source=f"worker:{worker['name']}",
        label=f"{worker['name']} ({connection['model']})",
        max_rounds=WORKER_MAX_ROUNDS,
        # Its tool calls hang under this worker in the Activities pane, so
        # the owner can see which worker did what rather than a flat list.
        parent_id=activity.id,
    )

    said: list[str] = []

    def record(role: str, content: str, blocks: Any = None, model_label: Any = None) -> int:
        # Thrown away with the worker. Nothing a worker says enters the
        # owner's conversation except through the result the Resident reads.
        return 0

    try:
        async for event in loop.run(
            [Message("owner", task)], _system(worker, host_facts), record
        ):
            kind = event["type"]
            if kind == "delta":
                said.append(event["text"])
            elif kind == "tool_end":
                result.calls.append(
                    {
                        "name": event["name"],
                        "arguments": event.get("arguments") or {},
                        "summary": event.get("summary") or "",
                        "is_error": bool(event.get("is_error")),
                    }
                )
            elif kind == "error":
                result.error = event["message"]
    except ModelError as exc:
        result.error = str(exc)
    except Exception as exc:                                  # noqa: BLE001
        # A worker falling over is the Resident's problem to report, not a
        # reason for the Resident's own turn to end.
        result.error = f"{exc.__class__.__name__}: {exc}"

    result.claimed = "".join(said)

    summary = f"{len(result.calls)} call{'s' if len(result.calls) != 1 else ''}"
    if result.error:
        activities.failed(activity, result.error, result.render())
    else:
        activities.completed(activity, summary, result.render())

    return result


def _connection_for(worker: dict[str, Any], store: Any) -> dict[str, Any] | None:
    """Which model this worker thinks with.

    Its own if it names one, otherwise the Aworg's worker connection. Falling
    back to the *Resident's* connection would be wrong in the expensive
    direction: a hosted frontier model answering fifteen delegated jobs an
    owner thought were going to the 2B on their own card.
    """
    if worker.get("connection_id"):
        found = store.get_connection(worker["connection_id"])
        if found:
            return found
    config = store.get_resident()
    for key in ("worker_connection_id",):
        if config.get(key):
            found = store.get_connection(config[key])
            if found:
                return found
    return None


def _system(worker: dict[str, Any], facts: dict[str, Any] | None = None) -> str:
    """What the worker is told about itself, and the little it needs about here.

    Not the Resident's full host block. That runs to several hundred tokens
    and would be a large share of a 2B's window spent on facts about a disk
    it is not going to think about.

    But not nothing either, and that was a real finding rather than a guess.
    With no machine facts at all, a runner told to "run python hello.py" did
    exactly that, hit the Windows Store stub, and failed -- and the Resident
    had to read the failure and dispatch a second worker with the full path.
    It recovered, which is the behaviour wanted, but it spent a round doing
    it. Two lines prevent that.

    So: which shell commands go through, and where a working interpreter is.
    Both are things a worker acts on directly. Everything else stays with the
    Resident, whose job is to put what matters into the task.
    """
    prompt = (worker.get("system_prompt") or "").strip() or (
        "You are a worker. Do exactly what the task asks, then report what "
        "you did and whether it worked."
    )
    if not facts:
        return prompt

    lines = [f"Commands run through {facts.get('shell', 'the system shell')}."]
    if facts.get("python_executable"):
        lines.append(
            f"A working Python is at {facts['python_executable']} -- use that "
            "full path rather than `python`."
        )
    if facts.get("stubs"):
        lines.append(
            f"These are on PATH but do NOT run: {', '.join(facts['stubs'])}."
        )
    return f"{prompt}\n\n{' '.join(lines)}"
