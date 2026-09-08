"""The Resident.

One ongoing conversation that outlives the browser tab and the process, and an
identity independent of whichever model is currently behind it. The owner can
change the mind the Resident thinks with, mid-conversation, and the Resident
carries on as itself. Everything here is arranged to make that true rather
than to make it look true.

What this file is *not* is the agent loop. Reaching for a tool, reading what
came back and going round again lives in agent.py, because a loop that is a
method on this class is a loop no worker can ever run. The Resident is one
caller of it: the one whose messages go in the owner's conversation and whose
tool scope is everything the owner has left enabled.

What stays here is what genuinely belongs to the inhabitant rather than to
the act of running a model -- which connection it thinks with, what it is
told about the machine it lives on, how much of the conversation still fits,
and the turn currently in progress.
"""

from __future__ import annotations

import asyncio
import json

from typing import Any, AsyncIterator

from . import host
from .activities import ActivityManager
from .agent import AgentLoop
from .models import Message, ModelError, build_adapter
from .tools import Registry, ToolContext
from .workers import run_worker
from .secrets import SecretStore, credential_ref
from .storage import Store


class Busy(Exception):
    """Raised when a reply is asked for while one is already in progress."""


class Turn:
    """A reply being generated, independent of whoever is watching it.

    A reply used to belong to one HTTP connection: close the tab and the
    generator was cancelled, the model's work thrown away, and the owner's
    message left standing with no answer. It also meant "stop" could only
    ever mean "stop listening" -- the model carried on, occupying the GPU
    for a reply nobody would see.

    So the turn lives here instead. The connection is a window onto it:
    several may watch, one may leave and come back, and everything said so
    far is replayed to whoever arrives late. Stopping it stops the work.
    """

    def __init__(self, conversation_id: str):
        self.conversation_id = conversation_id
        #: Every event so far, so a late or returning watcher misses nothing.
        self.events: list[dict[str, Any]] = []
        self.watchers: set[asyncio.Queue] = set()
        self.done = False
        self.stopping = False

    def emit(self, event: dict[str, Any]) -> None:
        self.events.append(event)
        for queue in list(self.watchers):
            queue.put_nowait(event)

    def finish(self) -> None:
        self.done = True
        for queue in list(self.watchers):
            queue.put_nowait(None)


class Resident:
    def __init__(self, store: Store, secrets: SecretStore, paths: Any = None):
        self.store = store
        self.secrets = secrets
        self.paths = paths
        #: What is happening right now, for anything that wants to watch.
        #: Held by the Resident today because it is the only thing running
        #: work; it belongs to the Aworg rather than to the Resident, and
        #: moves out when workers need to share one.
        self.activities = ActivityManager()
        #: Discovered once at startup. Whether a capability is *enabled* is
        #: asked of the store on every use rather than captured here, so the
        #: owner turning one off takes effect on the next call instead of at
        #: the next restart.
        self.registry = Registry(is_enabled=store.capability_enabled)
        #: Observed at startup rather than at install, because a machine
        #: surveyed at install time is wrong the first time its owner
        #: installs anything -- and refreshed as it ages, because an Aworg
        #: started once and left running for weeks would otherwise be
        #: working from a picture of the machine as it was on the first day.
        self.host = host.observe()
        #: At most one, because there is one Resident and one conversation.
        self.turn: Turn | None = None

    # -- state ----------------------------------------------------------

    def primary_connection(self) -> dict[str, Any] | None:
        connection_id = self.store.get_resident()["primary_connection_id"]
        if not connection_id:
            return None
        return self.store.get_connection(connection_id)

    def state(self) -> dict[str, Any]:
        """What the owner interface needs to describe the Resident right now."""
        connection = self.primary_connection()
        if connection is None:
            return {
                "status": "unconfigured",
                "detail": "No model is connected yet.",
                "model_label": None,
                "connection": None,
            }
        if not self.secrets.has(credential_ref(connection["id"])):
            return {
                "status": "unconfigured",
                "detail": f"{connection['name']} has no credential.",
                "model_label": _label(connection),
                "connection": connection,
            }
        return {
            "status": "present",
            "detail": "Resident is present.",
            "model_label": _label(connection),
            "connection": connection,
        }

    def conversation(self) -> dict[str, Any]:
        conversation_id = self.store.current_conversation_id()
        return {
            "id": conversation_id,
            "messages": self.store.messages(conversation_id),
        }

    # -- conversing -----------------------------------------------------

    #: Characters per token, for when the model cannot be asked. Measured
    #: against llama.cpp's own count on a real conversation: about 9% high,
    #: which errs the safe way.
    CHARS_PER_TOKEN = 3.6

    #: What a message costs beyond its text: the chat template's role markers
    #: and separators, a handful of tokens each. Small per message, hundreds
    #: across a long conversation, so it is counted rather than ignored.
    TOKENS_PER_MESSAGE = 5

    #: A deliberately generous characters-per-token, used only for the guard
    #: that stops a message being typed past what could ever be sent.
    #:
    #: The measured figure errs high, which is right for reporting -- it
    #: overstates the cost, so the ring never flatters. For a guard that is
    #: backwards: overstating would refuse text that would in fact have fit.
    #: A guard should only ever stop what is definitely too large, so it
    #: assumes the friendlier ratio.
    CHARS_PER_TOKEN_GENEROUS = 4.2

    #: Room left for the reply. A window is not a budget for history alone --
    #: the model still has to answer inside it, and a reasoning model answers
    #: at length. A fifth of the window, never less than 512 tokens.
    REPLY_RESERVE_SHARE = 5
    REPLY_RESERVE_MIN = 512

    @staticmethod
    def _converted(rows: list[dict[str, Any]]) -> list[tuple[int, Message]]:
        """Stored conversation rows as messages, each with the row it came from.

        The row id travels alongside because the interface has to be able to
        say which message the Resident's memory begins at, and counting
        positions in a rendered list is not the same question.
        """
        return [
            (
                row["id"],
                Message(
                    role=row["role"],
                    content=row["content"],
                    blocks=row.get("blocks"),
                ),
            )
            for row in rows
        ]

    @classmethod
    def _to_messages(cls, rows: list[dict[str, Any]]) -> list[Message]:
        """Stored conversation rows as the model layer's messages."""
        return [message for _, message in cls._converted(rows)]

    @staticmethod
    def _grouped(messages: list[Message]) -> list[list[Message]]:
        """Messages gathered into the units history can be trimmed by.

        Almost every group is one message. The exception is a tool exchange:
        a reply that asked for tools and the results that answered it are
        one indivisible thing, because both wire formats reject a result
        whose call is not there and a call whose result never came.

        Trimming by message would eventually cut between the two and break
        the conversation permanently -- not for one turn, since history only
        grows and the same cut would be made every turn after. So the edge
        falls between groups and never inside one.
        """
        groups: list[list[Message]] = []
        for message in messages:
            asked_for_tools = bool(
                groups
                and groups[-1]
                and groups[-1][-1].role == "resident"
                and any(
                    block.get("type") == "tool_use"
                    for block in (groups[-1][-1].blocks or [])
                )
            )
            if message.role == "tool" and asked_for_tools:
                groups[-1].append(message)
            else:
                groups.append([message])
        return groups

    async def refresh_host(self) -> None:
        """Look at the machine again if what we know has gone stale.

        On a worker thread: the look takes about two-thirds of a second, and
        holding the event loop for that would stall every other request in
        an interface that is streaming a reply at the time.
        """
        if not host.is_stale(self.host):
            return
        self.host = await asyncio.to_thread(host.observe)

    #: How many open tasks go into the prompt before it stops listing them
    #: and starts counting them. The plan has to be visible without becoming
    #: the reason there is no room to act on it.
    PLAN_IN_PROMPT = 12

    def plan_block(self) -> str:
        """The open plan, compactly, for the system prompt.

        This is what makes tasks worth having. The context window is a hard
        edge and history only grows, so the oldest messages stop being sent --
        in a real session here, twenty-six of forty-five messages were already
        invisible. A plan that lived only in the conversation would be
        forgotten exactly when the job got long enough to need one.

        The system prompt is rebuilt every turn and never truncated, so
        anything here is the one thing the Resident cannot lose. It is kept
        short for the same reason: every token spent describing the work is a
        token not available for doing it.
        """
        open_tasks = self.store.list_tasks(self.store.OPEN_STATES)
        if not open_tasks:
            return ""

        shown, extra = open_tasks[: self.PLAN_IN_PROMPT], len(open_tasks) - self.PLAN_IN_PROMPT
        lines = [
            f"  [{task['state']}] {task['id']}  {task['title']}"
            + (f" -- {task['note']}" if task["state"] == "blocked" and task["note"] else "")
            for task in shown
        ]
        if extra > 0:
            lines.append(f"  ... and {extra} more. Use list_tasks to see them.")

        counts = self.store.task_counts()
        done = counts.get("done", 0)
        return (
            "YOUR PLAN -- these are yours, written by you, and they outlive "
            "this conversation.\n"
            + "\n".join(lines)
            + (f"\n  ({done} already done.)" if done else "")
            + "\nKeep it current as you work: update_task to active when you "
            "start one and done once you have watched it succeed."
        )

    def system_prompt(self) -> str:
        """What the model is told about itself, where it is, and what it is doing.

        Three things, kept apart everywhere but here. The standing
        instructions are the owner's -- theirs to write and theirs to edit.
        The host block is observed fact, refreshed each start. Writing the
        facts into the owner's text would make them the owner's to maintain,
        and they would be wrong by the next time anything was installed.

        The plan is the Resident's own, and it is here rather than in the
        conversation because the conversation gets truncated and this does
        not.
        """
        instructions = self.store.get_resident()["system_prompt"]
        block = host.summary(self.host)
        plan = self.plan_block()

        parts = [instructions, block] + ([plan] if plan else [])
        return "\n\n---\n\n".join(part for part in parts if part).strip()

    def _estimate(self, text: str) -> int:
        return int(len(text) / self.CHARS_PER_TOKEN)

    def _offered_tools(self, adapter: Any, crew: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The tool descriptors this turn will send, or none if it cannot.

        Built here rather than left to the loop because the same list has to
        be measured before the conversation is fitted around it.
        """
        if not getattr(adapter, "supports_tools", False):
            return []
        return self.registry.descriptors(None, workers=crew)

    def _tools_cost(self, offered: list[dict[str, Any]]) -> int:
        """What the tool schemas cost, in tokens, on every request.

        Estimated from the JSON, which is what actually goes on the wire.
        Not a rounding error: six tools, one of them naming every configured
        worker and describing it, ran to well over a thousand tokens -- and
        an 8k window that ignored them sent a 10,070-token prompt and was
        refused.

        Rounded up rather than down. Overstating the cost drops one more
        message than strictly necessary; understating it produces a request
        the provider rejects outright, which ends the turn.
        """
        if not offered:
            return 0
        return self._estimate(json.dumps(offered)) + self.TOKENS_PER_MESSAGE * len(offered)

    def _fit(
        self,
        history: list[Message],
        system: str,
        window: int | None,
        tools_cost: int = 0,
    ) -> dict[str, Any]:
        """Choose the most recent messages that fit, newest first.

        A window is a hard edge, not a suggestion: a prompt past it is
        refused outright, and because history only grows, the first turn to
        cross would be followed by every subsequent turn crossing too. The
        conversation would be permanently broken rather than briefly. So the
        oldest messages stop being sent.

        Nothing is deleted. The conversation on disk keeps everything, always
        -- what is stored and what the model can see are different things,
        and this decides only the second. The interface says when they have
        diverged, because a Resident that has quietly forgotten the start of
        a conversation is worse than one that says so.

        Selection is by estimate rather than by asking the model to count
        each candidate set, which would be a round trip per step. The
        estimate runs about 9% high, so it keeps slightly less than it could
        -- the error falls on the safe side of the edge.
        """
        if not window:
            # Nobody has said how big the window is, so there is no edge to
            # stay inside. Send everything and let the provider object.
            return {"kept": history, "dropped": 0, "budget": None, "overflowing": False}

        reserve = max(self.REPLY_RESERVE_MIN, window // self.REPLY_RESERVE_SHARE)
        # Tool schemas are sent on every single request and are not free.
        # Leaving them out of the budget is how an 8k window received a
        # 10,070-token prompt and the provider refused it outright: six
        # tools, one of them carrying every worker's description, and none
        # of it counted. Whatever is charged for has to be subtracted here.
        budget = (
            window - reserve - tools_cost
            - self._estimate(system) - self.TOKENS_PER_MESSAGE
        )

        # Trimmed in groups rather than messages, so the cut never falls
        # inside a tool exchange. See _grouped.
        groups = self._grouped(history)
        kept_groups: list[list[Message]] = []
        used = 0
        for group in reversed(groups):
            cost = sum(
                self._estimate(message.content) + self.TOKENS_PER_MESSAGE
                for message in group
            )
            if used + cost > budget and kept_groups:
                break
            used += cost
            kept_groups.append(group)
        kept_groups.reverse()

        # The window has to open on something the owner said. Anthropic
        # refuses a conversation whose first message is the assistant's
        # outright, and a history that begins mid-exchange -- with the
        # Resident answering a question that is no longer there -- reads as
        # a non-sequitur to any model.
        #
        # So whole groups come off the front until one of the owner's
        # messages is first. Never the last group, because sending a
        # truncated conversation beats sending none.
        while len(kept_groups) > 1 and kept_groups[0][0].role != "owner":
            kept_groups.pop(0)

        kept = [message for group in kept_groups for message in group]

        # One message larger than the whole budget still gets sent: dropping
        # it would mean answering nothing at all. The provider will refuse,
        # and saying which message did it is more use than silence.
        overflowing = bool(kept) and used > budget
        return {
            "kept": kept,
            "dropped": len(history) - len(kept),
            "budget": budget,
            "overflowing": overflowing,
        }

    async def context_usage(self) -> dict[str, Any]:
        """How full the window is, built from exactly what the next turn sends.

        Exact when the model's server will count; estimated otherwise, and
        the answer says which. The window comes from the connection -- None
        if nobody has set it, in which case there is a count but no percent.
        """
        conversation_id = self.store.current_conversation_id()
        config = self.store.get_resident()
        pairs = self._converted(self.store.messages(conversation_id))
        history = [message for _, message in pairs]
        system = self.system_prompt()
        chars = len(system) + sum(len(m.content) for m in history)
        estimate = int(chars / self.CHARS_PER_TOKEN)

        connection = self.primary_connection()
        tokens, exact, window = estimate, False, None
        plan = {"kept": history, "dropped": 0, "overflowing": False}
        tools_cost = 0
        if connection is not None:
            window = connection.get("context")
            api_key = self.secrets.get(credential_ref(connection["id"]))
            # The same schemas the next turn will send, measured the same
            # way. A ring that ignores them reads comfortable right up to
            # the request the provider refuses.
            if api_key:
                tools_cost = self._tools_cost(
                    self._offered_tools(
                        build_adapter(connection, api_key),
                        self.store.list_workers(enabled_only=True),
                    )
                )
            plan = self._fit(history, system, window, tools_cost)
            if api_key:
                try:
                    counted = await build_adapter(connection, api_key).count_tokens(
                        plan["kept"], system
                    )
                except ModelError:
                    counted = None
                if counted is not None:
                    tokens, exact = counted, True
                else:
                    tokens = self._estimate(system) + sum(
                        self._estimate(m.content) + self.TOKENS_PER_MESSAGE
                        for m in plan["kept"]
                    )
                # Counted or estimated, the schemas ride along with it.
                tokens += tools_cost

        # Which stored message the Resident's memory actually begins at.
        # A count of dropped messages is not enough to place the seam: tool
        # exchanges are two rows and one thing on screen, so counting nodes
        # and counting messages give different answers, and the marker ends
        # up somewhere that is not the boundary it claims to be.
        visible_from = (
            pairs[plan["dropped"]][0]
            if plan["dropped"] and plan["dropped"] < len(pairs)
            else None
        )

        return {
            "tokens": tokens,
            "exact": exact,
            "window": window,
            "visible_from": visible_from,
            "percent": round(100 * tokens / window, 1) if window else None,
            # How many the model sees, and how many exist. When these differ
            # the conversation has outgrown the window.
            "messages": len(plan["kept"]),
            "stored": len(history),
            "dropped": plan["dropped"],
            "overflowing": plan["overflowing"],
            "chars_per_token": self.CHARS_PER_TOKEN,
            # The largest single message that could ever be sent. Dropping
            # history does not help past this: one message bigger than the
            # budget cannot fit however much room is made for it.
            "max_message_tokens": plan.get("budget"),
            "max_message_chars": (
                int(plan["budget"] * self.CHARS_PER_TOKEN_GENEROUS)
                if plan.get("budget") else None
            ),
        }

    def start_turn(self, text: str) -> "Turn":
        """Begin a reply, and return the turn it happens in.

        The work runs on its own task so that it outlives the request that
        asked for it. Whoever asked gets a window onto the turn; if they go
        away, the reply carries on and is waiting when they come back.
        """
        if self.turn is not None and not self.turn.done:
            raise Busy("The Resident is already answering.")

        turn = Turn(self.store.current_conversation_id())
        self.turn = turn

        async def run() -> None:
            try:
                async for event in self.respond_to(text, turn):
                    turn.emit(event)
            except Exception as exc:                      # noqa: BLE001
                # Nothing above is watching this task, so a failure here
                # would otherwise be silent and the turn would never end.
                turn.emit({"type": "error", "message": str(exc)})
            finally:
                turn.finish()

        turn.task = asyncio.create_task(run())
        return turn

    async def follow(self, turn: "Turn") -> AsyncIterator[dict[str, Any]]:
        """Watch a turn, from the beginning, however late you arrive."""
        queue: asyncio.Queue = asyncio.Queue()
        # Subscribing and taking the backlog happen together, with no await
        # between them, so an event cannot slip into both or neither.
        turn.watchers.add(queue)
        backlog = list(turn.events)
        finished = turn.done
        try:
            for event in backlog:
                yield event
            if finished:
                return
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event
        finally:
            turn.watchers.discard(queue)

    def stop_turn(self) -> bool:
        """Ask the reply in progress to stop. Whatever it said is kept."""
        if self.turn is None or self.turn.done:
            return False
        self.turn.stopping = True
        return True

    async def respond_to(
        self, text: str, turn: "Turn | None" = None
    ) -> AsyncIterator[dict[str, Any]]:
        """Take the owner's message and stream back the Resident's reply.

        Yields events rather than raw text so the owner interface can
        distinguish a reply arriving from a failure to reply.
        """
        conversation_id = self.store.current_conversation_id()

        # About to describe the machine to the model, so make sure the
        # description is not months old.
        await self.refresh_host()

        # The owner said it, so it happened. Record it before attempting a
        # reply -- if the model is unreachable, the message should not vanish.
        self.store.add_message(conversation_id, "owner", text)

        connection = self.primary_connection()
        if connection is None:
            yield {
                "type": "error",
                "message": "No model is connected. Open Settings to connect one.",
            }
            return

        api_key = self.secrets.get(credential_ref(connection["id"]))
        if not api_key:
            yield {
                "type": "error",
                "message": f"{connection['name']} has no credential. Add one in Settings.",
            }
            return

        history = self._to_messages(self.store.messages(conversation_id))
        adapter = build_adapter(connection, api_key)

        # Who the Resident may hand work to. Read fresh each turn rather than
        # captured, so a worker the owner adds mid-conversation is available
        # on the next message instead of the next restart.
        crew = self.store.list_workers(enabled_only=True)

        # Built before fitting, because the schemas are part of every request
        # and the conversation has to fit in what is left after them.
        offered = self._offered_tools(adapter, crew)

        # Only what fits goes to the model. Everything stays on disk.
        system = self.system_prompt()
        plan = self._fit(
            history, system, connection.get("context"), self._tools_cost(offered)
        )
        history = plan["kept"]
        if plan["dropped"] or plan["overflowing"]:
            yield {
                "type": "context",
                "dropped": plan["dropped"],
                "overflowing": plan["overflowing"],
            }

        label = _label(connection)

        def record(
            role: str,
            content: str,
            blocks: list[dict[str, Any]] | None = None,
            model_label: str | None = None,
        ) -> int:
            return self.store.add_message(
                conversation_id, role, content, model_label, blocks
            )

        async def spawn(name: str, task: str):
            """Start one worker. Returns None if there is no such worker.

            Handed to the tool layer rather than imported by it, so that
            `delegate` can start a worker without being able to reach
            anything else the Resident owns.
            """
            worker = self.store.worker_by_name(name)
            if worker is None or not worker["enabled"]:
                return None
            return await run_worker(
                worker,
                task,
                store=self.store,
                secrets=self.secrets,
                registry=self.registry,
                activities=self.activities,
                paths=self.paths,
                host_facts=self.host,
                parent_id=None,
            )

        loop = AgentLoop(
            adapter=adapter,
            registry=self.registry,
            tools=offered,
            context=ToolContext(
                paths=self.paths,
                activities=self.activities,
                host=self.host,
                spawn=spawn,
                workers=[w["name"] for w in crew],
                store=self.store,
            ),
            activities=self.activities,
            live={"workers": crew},
            # None: the Resident sees every tool the owner has left enabled.
            # A worker gets a list; that is the same argument, used
            # differently, which is the point of the loop not being a method
            # on this class any more.
            scope=None,
            source="resident",
            label=label,
        )

        async for event in loop.run(
            history,
            system,
            record,
            should_stop=lambda: turn is not None and turn.stopping,
        ):
            yield event
            if event["type"] == "stopped":
                yield {"type": "done", "model_label": label}
                return


def _label(connection: dict[str, Any]) -> str:
    """How a reply is attributed in the conversation.

    Showing which mind produced which reply is what makes switching models
    mid-conversation legible instead of mysterious.
    """
    return f"{connection['name']} ({connection['model']})"
