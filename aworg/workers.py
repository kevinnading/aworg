"""Workers: model runs the Resident starts, steers and stops.

There is no roster. The Resident spawns a worker for whatever it needs,
writes everything the worker is told, chooses its tools, skills and model,
and decides when it is finished with it. A worker runs in the background,
so the Resident can start as many as it likes and carry on; when one
replies it waits, holding its conversation, until the Resident sends it
further or stops it.

Workers live in this process. A restart ends them, the same as the programs
in the process table.

What comes back carries both what the worker said and the tool calls AWORG
saw it make, so a worker reporting success over calls that failed can be
told apart from one that succeeded.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from .activities import ActivityManager
from .agent import AgentLoop, _describe_arguments
from .models import Message, ModelError, build_adapter, needs_credential
from .secrets import credential_ref
from .tools import Registry, ToolContext

#: The capability whose tools start and steer workers. A worker is never
#: handed it: the pool belongs to the Resident.
WORKERS_CAPABILITY = "workers"

#: Characters per token, generously. Matches Resident.CHARS_PER_TOKEN_GENEROUS.
CHARS_PER_TOKEN_GENEROUS = 4.2

#: What a worker keeps back for its own reply, as a share of its window.
REPLY_SHARE = 4


class Worker:
    """One worker: its brief, its means, its conversation, its state."""

    #: working -> replied -> (message) -> working ... ; or failed / stopped.
    WORKING, REPLIED, FAILED, STOPPED = "working", "replied", "failed", "stopped"

    def __init__(
        self,
        name: str,
        system: str,
        tools: list[str] | None,
        connection: dict[str, Any],
    ):
        self.id = uuid.uuid4().hex[:6]
        self.name = name
        #: None means every tool the Resident has, except the worker tools.
        self.tools = tools
        #: Its whole system prompt, built by spawn_worker.
        self.system = system
        self.connection = connection
        self.history: list[Message] = []
        self.state = self.WORKING
        #: What it said at the end of its latest run.
        self.reply = ""
        #: Tool calls of its latest run, as AWORG observed them.
        self.calls: list[dict[str, Any]] = []
        self.error: str | None = None
        self.started = time.time()
        #: When its current or latest run began.
        self.run_started = self.started
        self.task: asyncio.Task | None = None
        #: How many runs it has started, and the last one the Resident read.
        self.runs = 0
        self.read = 0
        #: The Activity for its current or latest run; its tool calls hang
        #: under it, which is how the Workers pane shows what it is doing.
        self.activity_id: str | None = None
        self.done = asyncio.Event()

    @property
    def failed_calls(self) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["is_error"]]

    def line(self) -> str:
        """One row of a listing."""
        return (
            f"{self.id}  {self.name}  [{self.state}]  on {self.connection['name']}"
            f", {len(self.calls)} call{'s' if len(self.calls) != 1 else ''} this run"
        )

    @property
    def unread(self) -> bool:
        """Finished a run the Resident has not read."""
        return self.state != self.WORKING and self.read < self.runs

    def take(self) -> str:
        """render(), as the Resident reads it: a finished run is now read."""
        if self.state == self.WORKING:
            return self.render()
        self.read = self.runs
        return (
            f"{self.render()}\n\nStop it with stop_worker({self.id}) once you "
            "are done with it."
        )

    def render(self) -> str:
        """Its latest run in full: what it said, then what AWORG saw it do."""
        parts = [self.line()]
        if self.error:
            parts.append(f"\nIt did not finish: {self.error}")
        if self.state != self.WORKING:
            parts.append(f"\nIts reply:\n{self.reply.strip() or '(it said nothing)'}")
        if self.calls:
            lines = [
                f"  {'FAILED' if c['is_error'] else 'ok'}  {c['name']}"
                f"({c['arguments']}) -> {c['summary'] or 'no summary'}"
                for c in self.calls
            ]
            parts.append(
                f"\nTool calls AWORG observed ({len(self.calls)}"
                + (f", {len(self.failed_calls)} failed" if self.failed_calls else "")
                + "):\n" + "\n".join(lines)
            )
        else:
            parts.append("\nTool calls AWORG observed: none.")
        return "\n".join(parts)


class WorkerPool:
    """Every worker the Resident has started and not yet stopped."""

    def __init__(
        self,
        *,
        store: Any,
        secrets: Any,
        registry: Registry,
        activities: ActivityManager,
        paths: Any,
        host: Any,
        processes: Any,
        skills: Any,
        on_finish: Any = None,
    ):
        self.store = store
        self.secrets = secrets
        self.registry = registry
        self.activities = activities
        self.paths = paths
        #: A callable returning the current host facts; they are refreshed
        #: as the Aworg ages, so they are read at run time.
        self.host = host
        self.processes = processes
        self.skills = skills
        #: Called with a worker each time one of its runs ends on its own.
        self.on_finish = on_finish
        self.workers: dict[str, Worker] = {}

    # -- what the Resident is offered ------------------------------------

    def connections(self) -> list[dict[str, Any]]:
        """The connections a worker can be put on: enabled, and usable."""
        usable = []
        for c in self.store.list_connections():
            if not c.get("enabled"):
                continue
            if needs_credential(c) and not self.secrets.get(credential_ref(c["id"])):
                continue
            usable.append(c)
        return usable

    # -- lifecycle --------------------------------------------------------

    def spawn(
        self,
        *,
        name: str,
        task: str,
        system: str,
        tools: list[str] | None = None,
        connection: str = "",
    ) -> Worker:
        """Start a worker in the background and return it at once.

        Raises ValueError for a request that cannot start: an unknown
        connection, or no usable connection at all.
        """
        chosen = self._connection(connection)
        if tools is not None:
            unknown = sorted(set(tools) - set(self.grantable()))
            if unknown:
                raise ValueError(
                    f"Not tools you can give a worker: {', '.join(unknown)}."
                )
        worker = Worker(name or "worker", system, tools, chosen)
        worker.history.append(Message("owner", task))
        self.workers[worker.id] = worker
        self._start(worker)
        return worker

    def message(self, worker_id: str, text: str) -> Worker:
        worker = self.get(worker_id)
        if worker.state == Worker.WORKING:
            raise ValueError(f"{worker.id} is still working.")
        if worker.state == Worker.STOPPED:
            raise ValueError(f"{worker.id} was stopped.")
        worker.history.append(Message("owner", text))
        self._start(worker)
        return worker

    def stop(self, worker_id: str) -> Worker:
        """Cancel and discard a worker. Read its reply first if unread."""
        worker = self.get(worker_id)
        worker.last_words = ""
        if worker.unread:
            worker.read = worker.runs
            worker.last_words = worker.render()
        if worker.task is not None and not worker.task.done():
            worker.task.cancel()
        worker.state = Worker.STOPPED
        worker.done.set()
        del self.workers[worker.id]
        return worker

    def stop_all(self) -> None:
        for worker_id in list(self.workers):
            self.stop(worker_id)

    def get(self, worker_id: str) -> Worker:
        worker = self.workers.get(str(worker_id).strip())
        if worker is None:
            known = ", ".join(self.workers) or "none"
            raise KeyError(f"No worker {worker_id!r}. Current workers: {known}.")
        return worker

    def all(self) -> list[Worker]:
        return list(self.workers.values())

    # -- running ------------------------------------------------------------

    def _connection(self, name: str) -> dict[str, Any]:
        usable = self.connections()
        if not usable:
            raise ValueError("No usable model connection is enabled.")
        if name:
            for c in usable:
                if c["name"].lower() == name.strip().lower():
                    return c
            raise ValueError(
                f"No usable connection called {name!r}. Usable: "
                + ", ".join(c["name"] for c in usable) + "."
            )
        primary = self.store.get_resident().get("primary_connection_id")
        for c in usable:
            if c["id"] == primary:
                return c
        return usable[0]

    def _start(self, worker: Worker) -> None:
        worker.state = Worker.WORKING
        worker.runs += 1
        worker.run_started = time.time()
        worker.reply, worker.calls, worker.error = "", [], None
        worker.done = asyncio.Event()
        worker.task = asyncio.create_task(self._run(worker))

    def grantable(self) -> list[str]:
        """Every tool the Resident has that a worker may be given."""
        return sorted(
            spec.name
            for spec in self.registry.specs(None)
            if spec.capability != WORKERS_CAPABILITY
        )

    def _scope(self, worker: Worker) -> list[str]:
        """The tools this worker may call: what it was given, never the pool."""
        own = {
            spec.name
            for spec in self.registry.specs(None)
            if spec.capability != WORKERS_CAPABILITY
        }
        if worker.tools is None:
            return sorted(own)
        granted = set()
        for name in worker.tools:
            capability = self.registry.get_capability(name)
            if capability is not None and capability.id != WORKERS_CAPABILITY:
                granted.update(s.name for s in capability.tools)
            elif name in own:
                granted.add(name)
        return sorted(granted & own)

    async def _run(self, worker: Worker) -> None:
        connection = worker.connection
        api_key = self.secrets.get(credential_ref(connection["id"])) or ""
        activity = self.activities.create(
            kind="worker",
            label=worker.name,
            source="resident",
            detail=(worker.history[-1].content or "")[:80],
        )
        self.activities.started(activity)
        worker.activity_id = activity.id

        loop = AgentLoop(
            adapter=build_adapter(connection, api_key),
            registry=self.registry,
            context=ToolContext(
                paths=self.paths,
                activities=self.activities,
                host=self.host(),
                processes=self.processes,
                skills=self.skills,
                result_limit=_result_limit(connection),
            ),
            activities=self.activities,
            scope=self._scope(worker),
            source=f"worker:{worker.id}",
            label=f"{worker.name} ({connection['model']})",
            parent_id=activity.id,
        )

        said: list[str] = []
        grown: list[Message] = []

        def record(role: str, content: str, blocks: Any = None,
                   model_label: Any = None, thinking: Any = None,
                   thinking_for: Any = None) -> int:
            # Kept on the worker, so a message sent to it later continues
            # this conversation. Nothing enters the owner's.
            grown.append(Message(role, content, blocks))
            return 0

        try:
            async for event in loop.run(worker.history, worker.system, record):
                kind = event["type"]
                if kind == "delta":
                    said.append(event["text"])
                elif kind == "tool_end":
                    worker.calls.append({
                        "name": event["name"],
                        # A description, not the arguments: a write_file's
                        # content is the whole file.
                        "arguments": _describe_arguments(event.get("arguments") or {}),
                        "summary": event.get("summary") or "",
                        "is_error": bool(event.get("is_error")),
                    })
                elif kind == "error":
                    worker.error = event["message"]
        except asyncio.CancelledError:
            self.activities.failed(activity, "stopped", worker.render())
            raise
        except ModelError as exc:
            worker.error = str(exc)
        except Exception as exc:                                  # noqa: BLE001
            worker.error = f"{exc.__class__.__name__}: {exc}"

        worker.history.extend(grown)
        worker.reply = "".join(said)
        worker.state = Worker.FAILED if worker.error else Worker.REPLIED
        worker.done.set()
        if self.on_finish is not None:
            try:
                self.on_finish(worker)
            except Exception:                                 # noqa: BLE001
                pass

        summary = f"{len(worker.calls)} call{'s' if len(worker.calls) != 1 else ''}"
        if worker.error:
            self.activities.failed(activity, worker.error, worker.render())
        else:
            self.activities.completed(activity, summary, worker.render())


def _result_limit(connection: dict[str, Any]) -> int | None:
    """The largest tool result this worker's model could carry, if known."""
    window = connection.get("context")
    if not window or window <= 0:
        return None
    return int((window - window // REPLY_SHARE) * CHARS_PER_TOKEN_GENEROUS)
