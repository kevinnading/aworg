"""The Resident.

In Milestone 1 the Resident can only converse -- it has no tools, no workspace
access, and no ability to act. What it does have is continuity: one ongoing
conversation that outlives the browser tab and the process, and an identity
that is independent of whichever model is currently behind it.

That independence is the point of this milestone. The owner can change the mind
the Resident thinks with, mid-conversation, and the Resident carries on as
itself. Everything here is arranged to make that true rather than to make it
look true.
"""

from __future__ import annotations

import asyncio
import json

from typing import Any, AsyncIterator

from . import host
from .tools import build_registry
from .models import Message, ModelError, ToolCall, build_adapter
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
        #: Observed at startup rather than at install, because a machine
        #: surveyed at install time is wrong the first time its owner
        #: installs anything -- and refreshed as it ages, because an Aworg
        #: started once and left running for weeks would otherwise be
        #: working from a picture of the machine as it was on the first day.
        self.host = host.observe()
        #: At most one, because there is one Resident and one conversation.
        self.turn: Turn | None = None
        #: What it can do. Small on purpose; see aworg/tools/__init__.py.
        self.tools = build_registry(paths.workspace) if paths else None

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

    #: How many times round the loop before stopping and saying so. High
    #: enough for real work -- installing something, building it, checking it
    #: -- and low enough that a model stuck in a cycle costs minutes rather
    #: than a night. Reaching it is reported, never silent.
    MAX_STEPS = 16

    @staticmethod
    def _to_messages(rows: list[dict[str, Any]]) -> list[Message]:
        """Stored conversation rows as the model layer's messages.

        Tool exchanges are kept in the conversation like anything else --
        they are what happened -- so they come back out of storage as the
        calls and results they were, with their ids paired.
        """
        messages: list[Message] = []
        for row in rows:
            role, content = row["role"], row["content"]
            if role == "tool_call":
                try:
                    payload = json.loads(content)
                except (ValueError, TypeError):
                    continue
                messages.append(Message(
                    role="resident",
                    content=payload.get("said", ""),
                    tool_calls=[
                        ToolCall(id=c["id"], name=c["name"], arguments=c["arguments"])
                        for c in payload.get("calls", [])
                    ],
                ))
            elif role == "tool_result":
                try:
                    payload = json.loads(content)
                except (ValueError, TypeError):
                    continue
                messages.append(Message(
                    role="tool_result",
                    content=payload.get("output", ""),
                    tool_call_id=payload.get("id"),
                ))
            else:
                messages.append(Message(role=role, content=content))
        return messages

    async def refresh_host(self) -> None:
        """Look at the machine again if what we know has gone stale.

        On a worker thread: the look takes about a quarter of a second, and
        holding the event loop for that would stall every other request in
        an interface that is streaming a reply at the time.
        """
        if not host.is_stale(self.host):
            return
        self.host = await asyncio.to_thread(host.observe)

    def system_prompt(self) -> str:
        """What the model is told about itself, and about where it is.

        Two things, kept apart everywhere but here. The standing
        instructions are the owner's -- theirs to write and theirs to edit.
        The host block is observed fact, refreshed each start. Writing the
        facts into the owner's text would make them the owner's to maintain,
        and they would be wrong by the next time anything was installed.
        """
        instructions = self.store.get_resident()["system_prompt"]
        block = host.summary(self.host)

        if self.tools and len(self.tools):
            # Stated as present fact, because the conversation may contradict
            # it. A Resident that spent weeks correctly saying it had no
            # tools will go on saying so after it is given some: the model is
            # being consistent with its own past, which is usually a virtue.
            # Observed in exactly that form -- six past denials inside a
            # 76-message history were enough to make it refuse a shell it had
            # been handed, with the tool definitions on the wire in front of
            # it. The remedy is to say plainly which of the two is true now.
            block += (
                f"\n\nYou have these tools available right now: "
                f"{', '.join(self.tools.names())}. If earlier in this "
                "conversation you said you had no tools and could not act, "
                "that was true then and is not true now. Use them."
            )

        return f"{instructions}\n\n---\n\n{block}".strip()

    def _estimate(self, text: str) -> int:
        return int(len(text) / self.CHARS_PER_TOKEN)

    def _fit(self, history: list[Message], system: str, window: int | None) -> dict[str, Any]:
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
        budget = window - reserve - self._estimate(system) - self.TOKENS_PER_MESSAGE

        kept: list[Message] = []
        used = 0
        for message in reversed(history):
            cost = self._estimate(message.content) + self.TOKENS_PER_MESSAGE
            if used + cost > budget and kept:
                break
            used += cost
            kept.append(message)
        kept.reverse()

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
        history = self._to_messages(self.store.messages(conversation_id))
        system = self.system_prompt()
        chars = len(system) + sum(len(m.content) for m in history)
        estimate = int(chars / self.CHARS_PER_TOKEN)

        connection = self.primary_connection()
        tokens, exact, window = estimate, False, None
        plan = {"kept": history, "dropped": 0, "overflowing": False}
        if connection is not None:
            window = connection.get("context")
            plan = self._fit(history, system, window)
            api_key = self.secrets.get(credential_ref(connection["id"]))
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

        return {
            "tokens": tokens,
            "exact": exact,
            "window": window,
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

    def _stop_tools(self) -> None:
        """Kill anything a stopped turn left running.

        A build that nobody is waiting for is a build that should not still
        be holding the machine.
        """
        for tool in getattr(self.tools, "_tools", {}).values():
            stopper = getattr(tool, "stop_all", None)
            if stopper:
                stopper()

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

        resident_config = self.store.get_resident()
        history = [
            Message(role=m["role"], content=m["content"])
            for m in self.store.messages(conversation_id)
        ]

        # Only what fits goes to the model. Everything stays on disk.
        system = self.system_prompt()
        plan = self._fit(history, system, connection.get("context"))
        history = plan["kept"]
        if plan["dropped"] or plan["overflowing"]:
            yield {
                "type": "context",
                "dropped": plan["dropped"],
                "overflowing": plan["overflowing"],
            }

        label = _label(connection)
        adapter = build_adapter(connection, api_key)
        definitions = self.tools.definitions() if self.tools else None

        stopped = False
        said_anything = False

        # Round the loop: the model speaks, and either it is finished or it
        # has asked for something. If it asked, the tools run, the answers go
        # back, and it speaks again with them in hand. A turn is over when the
        # model stops asking -- not when it stops talking.
        for step in range(self.MAX_STEPS):
            collected: list[str] = []
            calls: list[ToolCall] = []
            thought = False

            try:
                async for fragment in adapter.stream(
                    history, system=system, tools=definitions
                ):
                    # Checked between fragments rather than by cancelling the
                    # task: leaving the loop closes the model's stream on the
                    # way out, and whatever was already said is kept below
                    # exactly as it would be after a normal finish.
                    if turn is not None and turn.stopping:
                        stopped = True
                        break
                    if fragment.kind == "thinking":
                        # Thinking is not what the Resident said, so it is
                        # never kept. It is still reported, because a model
                        # silent for thirty seconds is indistinguishable from
                        # one that has hung.
                        thought = True
                        yield {"type": "thinking", "text": fragment.text}
                    elif fragment.kind == "tool_call":
                        calls.append(fragment.call)
                    else:
                        collected.append(fragment.text)
                        yield {"type": "delta", "text": fragment.text}
            except ModelError as exc:
                if collected:
                    self.store.add_message(
                        conversation_id, "resident", "".join(collected), label
                    )
                yield {"type": "error", "message": str(exc)}
                return

            said = "".join(collected)
            said_anything = said_anything or bool(said.strip())

            if stopped:
                # Stopping mid-step: keep what was said, abandon what was
                # asked for. Running a tool nobody is waiting on is work the
                # owner has just said they do not want.
                if said.strip():
                    self.store.add_message(conversation_id, "resident", said, label)
                if self.tools:
                    self._stop_tools()
                yield {"type": "stopped", "partial": bool(said.strip())}
                yield {"type": "done", "model_label": label}
                return

            if not calls:
                # Nothing asked for: the turn is finished.
                if said.strip():
                    self.store.add_message(conversation_id, "resident", said, label)
                elif thought and not said_anything:
                    yield {
                        "type": "error",
                        "message": (
                            f"{label} spent its whole reply thinking and never "
                            "answered. Its reasoning budget is likely too small "
                            "for this request."
                        ),
                    }
                    return
                yield {"type": "done", "model_label": label}
                return

            # It asked for something. Record the asking as part of the
            # conversation -- it is what happened, and the model needs to see
            # its own request next time round or it will ask again.
            self.store.add_message(
                conversation_id,
                "tool_call",
                json.dumps({
                    "said": said,
                    "calls": [
                        {"id": c.id, "name": c.name, "arguments": c.arguments}
                        for c in calls
                    ],
                }),
                label,
            )
            for call in calls:
                yield {
                    "type": "tool_call",
                    "id": call.id,
                    "name": call.name,
                    "arguments": call.arguments,
                }

            for call in calls:
                if turn is not None and turn.stopping:
                    stopped = True
                    break
                result = await self.tools.invoke(call.name, call.arguments)
                # What AWORG observed is stored beside what the model will be
                # told, so that a later claim about this step can be checked
                # against the record rather than taken on trust.
                self.store.add_message(
                    conversation_id,
                    "tool_result",
                    json.dumps({
                        "id": call.id,
                        "name": call.name,
                        "output": result.for_model(),
                        "observed": result.observed,
                        "failed": result.failed,
                    }),
                    label,
                )
                yield {
                    "type": "tool_result",
                    "id": call.id,
                    "name": call.name,
                    "failed": result.failed,
                    "observed": result.observed,
                    "output": result.output,
                }

            if stopped:
                if self.tools:
                    self._stop_tools()
                yield {"type": "stopped", "partial": said_anything}
                yield {"type": "done", "model_label": label}
                return

            # Rebuild from storage rather than appending in memory, so that
            # what goes back to the model is exactly what was written down.
            history = self._to_messages(self.store.messages(conversation_id))
            plan = self._fit(history, system, connection.get("context"))
            history = plan["kept"]
            if plan["dropped"]:
                yield {
                    "type": "context",
                    "dropped": plan["dropped"],
                    "overflowing": plan["overflowing"],
                }

        # The ceiling. Said plainly rather than passed off as a finished
        # answer, because an owner reading a reply that stops mid-task
        # deserves to know it was cut off rather than concluded.
        yield {
            "type": "error",
            "message": (
                f"Stopped after {self.MAX_STEPS} steps without finishing. "
                "Everything done so far is above, and in the workspace."
            ),
        }
        yield {"type": "done", "model_label": label}


def _label(connection: dict[str, Any]) -> str:
    """How a reply is attributed in the conversation.

    Showing which mind produced which reply is what makes switching models
    mid-conversation legible instead of mysterious.
    """
    return f"{connection['name']} ({connection['model']})"
