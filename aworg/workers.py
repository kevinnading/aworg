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
from .agent import AgentLoop, _describe_arguments
from .models import Message, ModelError, build_adapter
from .secrets import credential_ref
from .tools import Registry, ToolContext


#: Fewer than the Resident, but not by much, and for a different reason than
#: it used to be. This was six, on the theory that a small model going round
#: eight times has lost the thread. That theory was wrong in the same way the
#: Resident's ten was: it stops a worker doing a genuinely long job, and a
#: worker that has actually lost the thread is caught by the loop's
#: repetition check rather than by a count.
#:
#: Lower than 200 only because the Resident is blocked while this runs, so a
#: worker that somehow gets past the repetition check should give the turn
#: back sooner than the Resident would give it back to the owner.
WORKER_MAX_ROUNDS = 60


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
    processes: Any = None,
    parent_id: str | None = None,
    skills: Any = None,
    journal: Any = None,
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
            "No model is connected at all. Connect one in Settings, and "
            "optionally give workers a cheaper one of their own."
        )
        return result

    # Running on the Resident's own model because nothing cheaper was set.
    #
    # Said out loud rather than discovered on a bill. The fall-through is
    # what makes delegation work on an Aworg nobody has configured, and the
    # whole objection to it was the cost -- so the cost is reported. The
    # Living Log is where a state of affairs the owner would want to find
    # later belongs.
    config = store.get_resident()
    if (
        journal is not None
        and not worker.get("connection_id")
        and not config.get("worker_connection_id")
    ):
        journal.note_once(
            f"Workers are running on {connection['name']}",
            kind="worker",
            detail=(
                "No separate worker connection is set, so delegated work goes "
                "to the same model the Resident thinks with. That works, and "
                "on a hosted model it is charged like any other request. "
                "Settings can point workers at something cheaper."
            ),
        )

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
            paths=paths,
            activities=activities,
            host=host_facts,
            # Shared with the Resident on purpose. A worker that started a
            # server on its own private table would leave something running
            # that nothing could later find or stop.
            processes=processes,
            # From its own connection, which may be a far smaller model than
            # the Resident's. A worker on an 8k window and a Resident on a
            # million should not be handed the same ceiling, and neither
            # should be handed a constant.
            result_limit=_result_limit(connection),
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
            [Message("owner", task)],
            _system(
                worker,
                host_facts,
                workspace=paths.workspace if paths is not None else None,
                library=skills,
            ),
            record,
        ):
            kind = event["type"]
            if kind == "delta":
                said.append(event["text"])
            elif kind == "tool_end":
                result.calls.append(
                    {
                        "name": event["name"],
                        # A description, not the arguments.
                        #
                        # This held the whole dict, and a write_file's
                        # content argument is the whole file -- so a builder
                        # that wrote five pages put all five into the
                        # Resident's context through its own report. One such
                        # report came to 12,971 tokens, which is the opposite
                        # of what delegating is for: the point of a worker is
                        # that the work happens in a context that is then
                        # thrown away.
                        "arguments": _describe_arguments(
                            event.get("arguments") or {}
                        ),
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


#: Characters per token, generously. Matches Resident.CHARS_PER_TOKEN_GENEROUS
#: and is duplicated for the same reason panes.py duplicates its own: this
#: module has no business importing the Resident, and the number belongs to
#: the tokenizer rather than to either of them.
CHARS_PER_TOKEN_GENEROUS = 4.2

#: What a worker keeps back for its own reply, as a share of its window.
#: A result that filled the whole window would leave nothing to answer with.
REPLY_SHARE = 4


def _result_limit(connection: dict[str, Any]) -> int | None:
    """The largest tool result this worker's model could carry.

    None where the window is unknown, which is the ordinary case for a
    hosted model and means nothing is cut. A worker on a small local model
    gets a real ceiling, because there the edge is real.
    """
    window = connection.get("context")
    if not window or window <= 0:
        return None
    return int((window - window // REPLY_SHARE) * CHARS_PER_TOKEN_GENEROUS)


def _connection_for(worker: dict[str, Any], store: Any) -> dict[str, Any] | None:
    """Which model this worker thinks with.

    Its own if it names one, then the Aworg's worker connection, then the
    Resident's own.

    That last fall-through was deliberately absent, on the argument that it
    was wrong in the expensive direction -- a hosted frontier model answering
    fifteen delegated jobs the owner thought were going to the 2B on their
    own card. The argument was sound and the conclusion was not, because the
    alternative it produced is worse in every case: an Aworg where nobody
    has set a worker connection has no workers at all, and the Resident
    discovers this by trying to delegate and being told to go and configure
    something.

    That is what happened. A Resident planned four tasks, handed the first to
    the builder, got "No model is connected for workers", and did the whole
    job itself -- one wasted round trip, and a division of labour silently
    abandoned on an Aworg whose owner had changed nothing.

    Spending the owner's money without being asked is a real cost, so it is
    reported rather than hidden: a worker running on the Resident's own
    connection says so in the Living Log the first time it happens. Cheap
    workers stay one setting away, and the setting is now an optimisation
    rather than a precondition for delegation working at all.
    """
    if worker.get("connection_id"):
        found = store.get_connection(worker["connection_id"])
        if found:
            return found
    config = store.get_resident()
    for key in ("worker_connection_id", "primary_connection_id"):
        if config.get(key):
            found = store.get_connection(config[key])
            if found:
                return found
    return None


def _system(
    worker: dict[str, Any],
    facts: dict[str, Any] | None = None,
    workspace: Any = None,
    library: Any = None,
) -> str:
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

    So: which shell commands go through, where a working interpreter is, and
    where its own work is supposed to land. All three are things a worker
    acts on directly. Everything else stays with the Resident, whose job is
    to put what matters into the task.

    The workspace earns its line for the same reason the interpreter did. A
    worker never told where it is picks an absolute path out of the air --
    observed repeatedly, and the paths it picked were inside AWORG's own
    source tree, because that was the only directory anything had named to
    it.
    """
    prompt = (worker.get("system_prompt") or "").strip() or (
        "You are a worker. Do exactly what the task asks, then report what "
        "you did and whether it worked."
    )
    prompt += _skills_block(worker, library)
    if not facts:
        return prompt

    lines = []
    if workspace:
        lines.append(
            f"Work in {workspace} unless the task names somewhere else -- a "
            "relative path goes there. Do not invent a directory."
        )
    lines.append(f"Commands run through {facts.get('shell', 'the system shell')}.")
    if facts.get("python_executable"):
        lines.append(
            f"A working Python is at {facts['python_executable']} -- use that "
            "full path rather than `python`."
        )
    # The stub warning that used to sit here has gone with the scan that made
    # it necessary. It only ever corrected a claim the tool list made -- and
    # with nothing advertising a `python` on PATH, the positive instruction
    # above is the whole of what a worker needs: here is one that works, use
    # it by path.
    return f"{prompt}\n\n{' '.join(lines)}"


def _skills_block(worker: dict[str, Any], library: Any) -> str:
    """The worker's skills, in full, in front of it.

    **Given, not offered.** The Resident gets descriptions and fetches a body
    with read_skill when it judges one applies; a worker gets the body
    outright. That is a deliberate departure from progressive disclosure, and
    it is the right one here for two separate reasons.

    The first is that progressive disclosure solves a problem a worker does
    not have. It exists so a Resident carrying a dozen skills across an
    open-ended conversation pays for a paragraph rather than a book. A worker
    is a fresh context for one bounded job, holding the two or three skills
    its owner scoped it to. There is nothing to defer, and deferring would
    cost it a round trip out of the few it has.

    The second is measured. Asked plainly, a local model reaches for a
    matching skill about one time in six; told to read a named one, it does
    so four times out of four, on two unrelated model families. The reliable
    half of that is being told. So the Resident's judgement -- which worker
    should do this -- is what routes a skill to where it is needed, and by
    the time the worker sees it there is no decision left to get wrong.

    A named skill that no longer exists is skipped rather than raised on. An
    owner who deletes a skill file should not find three workers refusing to
    start.
    """
    names = worker.get("skills") or []
    if not names or library is None:
        return ""

    bodies = []
    for name in names:
        skill = library.get_any(name)
        if skill is None:
            continue
        bodies.append(f"## {skill.name}\n\n{skill.body().strip()}")
    if not bodies:
        return ""

    return (
        "\n\nThese are this machine's own conventions for the kind of work "
        "you do. They are not general good practice and you could not have "
        "guessed them. Follow them exactly, in preference to how you would "
        "normally do it.\n\n" + "\n\n".join(bodies)
    )
