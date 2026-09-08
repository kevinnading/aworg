"""The agent loop: talk, reach for tools, look at what came back, carry on.

This is a free-standing object rather than a method on the Resident, and that
is the whole reason it exists as its own file. The previous version lived on
`Resident`, which meant a worker could never run one -- the loop was the
property of a particular inhabitant rather than something anything with a
model behind it could do. A worker is a connection, a prompt and a tool
scope, and it needs exactly this and nothing the Resident owns.

So the loop is given everything it works with and keeps none of it: an
adapter to think with, a registry to reach into, a scope saying which tools
it may see, and a `record` callback for putting messages somewhere. The
Resident's callback writes to the owner's conversation. A worker's will
append to its own scratch history, which is discarded when the job is done.

What the loop does not do is decide anything about presentation, persistence,
or what deserves remembering. It yields events; whoever is running it decides
what those mean.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, AsyncIterator, Callable, Iterable

from .activities import ActivityManager
from .models import Message, ModelError, ToolCall
from .tools import Registry, ToolContext, ToolResult


#: How many times round before giving up. A round is one reply plus whatever
#: tools it asked for, so this is the number of *consecutive* tool-using
#: replies allowed before the loop insists on stopping.
#:
#: It exists for the small models this is built against, which get stuck: a
#: 2B that reads the same file four times is not converging on anything, and
#: without a ceiling it will keep going until the owner notices. Ten is
#: comfortably more than real work needs and short of an afternoon's tokens.
MAX_ROUNDS = 10


class AgentLoop:
    """One model, some tools, and the patience to go round until it is done."""

    def __init__(
        self,
        adapter: Any,
        registry: Registry,
        context: ToolContext,
        activities: ActivityManager,
        scope: Iterable[str] | None = None,
        source: str = "resident",
        label: str = "",
        max_rounds: int = MAX_ROUNDS,
        parent_id: str | None = None,
        live: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
    ):
        self.adapter = adapter
        self.registry = registry
        self.context = context
        self.activities = activities
        #: Which tools this caller may see. None means everything enabled --
        #: the Resident. A worker is handed a list.
        self.scope = scope
        self.source = source
        #: How a reply is attributed in the conversation.
        self.label = label
        self.max_rounds = max_rounds
        #: The Activity every tool call hangs under, if this loop is itself
        #: something being watched. A worker sets it so its calls nest
        #: beneath it in the pane rather than appearing in a flat list with
        #: no sign of who ran them.
        self.parent_id = parent_id
        #: State a self-describing tool needs at the moment it is offered --
        #: today just the worker list, which decides whether `delegate`
        #: appears at all and what its enumeration contains.
        self.live = live or {}
        #: Precomputed descriptors, when the caller has already built them --
        #: the Resident does, because it has to measure what the tool schemas
        #: cost before deciding how much conversation fits alongside them.
        #: Measuring one list and sending another would be the same bug in a
        #: quieter form.
        self._tools = tools

    def tools(self) -> list[dict[str, Any]]:
        """The tool descriptors this caller gets, or none if it cannot use them.

        A provider whose adapter cannot carry tool calls is handed nothing
        rather than a list it would have to ignore. The conversation still
        works; the Resident simply has no hands on that connection, and the
        interface says so rather than leaving the owner to wonder why it
        never does anything.
        """
        if not getattr(self.adapter, "supports_tools", False):
            return []
        if self._tools is not None:
            return self._tools
        return self.registry.descriptors(self.scope, **self.live)

    async def run(
        self,
        history: list[Message],
        system: str,
        record: Callable[..., Any],
        should_stop: Callable[[], bool] = lambda: False,
    ) -> AsyncIterator[dict[str, Any]]:
        """Run until the model stops asking for tools, and yield what happens.

        `history` is the conversation so far. The loop works on a copy of it,
        growing that copy with each reply and each set of results -- the
        model has to see its own tool calls answered on the next round or it
        will simply ask again. The caller's list is left alone, because the
        caller reads its history back from wherever `record` put it and two
        things appending to one list would double every message.

        `record` is called for every message that should be kept. It is a
        callback rather than a store so that a worker can run this loop
        without writing into the owner's conversation.
        """
        tools = self.tools()
        working = list(history)

        for round_number in range(self.max_rounds):
            said: list[str] = []
            calls: list[ToolCall] = []
            thought = False

            try:
                async for fragment in self.adapter.stream(
                    working, system=system, tools=tools or None
                ):
                    if should_stop():
                        yield {"type": "stopped", "partial": bool("".join(said).strip())}
                        self._keep(record, working, "".join(said), [])
                        return

                    if fragment.kind == "thinking":
                        thought = True
                        yield {"type": "thinking", "text": fragment.text}
                    elif fragment.kind == "tool_use" and fragment.tool_call:
                        calls.append(fragment.tool_call)
                    else:
                        said.append(fragment.text)
                        yield {"type": "delta", "text": fragment.text}
            except ModelError as exc:
                # Whatever was said before the failure is kept. A reply that
                # got halfway and then lost the connection is still something
                # the owner watched arrive.
                if "".join(said).strip() or calls:
                    self._keep(record, working, "".join(said), calls)
                yield {"type": "error", "message": str(exc)}
                return

            text = "".join(said)

            if not calls:
                if text.strip():
                    self._keep(record, working, text, [])
                elif thought:
                    yield {
                        "type": "error",
                        "message": (
                            f"{self.label or 'The model'} spent its whole reply "
                            "thinking and never answered. Its reasoning budget "
                            "is likely too small for this request."
                        ),
                    }
                    return
                yield {"type": "done", "model_label": self.label}
                return

            # The reply asked for tools, so it is recorded with them attached
            # before any of them run. If AWORG stops here the conversation
            # still says what was asked for, and the model reading it back
            # sees a request it made rather than prose about one.
            self._keep(record, working, text, calls)

            results: list[dict[str, Any]] = []
            for index, call in enumerate(calls):
                async for event in self._run_tool(call, results):
                    yield event
                if should_stop():
                    # Whatever was not reached still has to be answered. The
                    # reply asking for all of them is already recorded, and a
                    # tool_use with no tool_result is rejected outright by
                    # both wire formats -- so stopping here without this
                    # would break the conversation permanently, exactly the
                    # way a cut inside a tool exchange does. Nothing ran;
                    # saying so is both true and valid.
                    for skipped in calls[index + 1:]:
                        yield self._cancel(skipped, results)
                    break

            self._keep_results(record, working, results)

            if should_stop():
                yield {"type": "stopped", "partial": True}
                return

        # Out of rounds. Said plainly rather than silently returning whatever
        # the last reply happened to be, because a loop that gave up is not
        # the same as one that finished and the owner should not have to
        # guess which they are looking at.
        yield {
            "type": "error",
            "message": (
                f"Stopped after {self.max_rounds} rounds of tool use without "
                "reaching an answer. The last thing tried is above."
            ),
        }

    # -- one tool call --------------------------------------------------

    async def _run_tool(
        self, call: ToolCall, results: list[dict[str, Any]]
    ) -> AsyncIterator[dict[str, Any]]:
        """Run one tool as an Activity, and append its result.

        The Activity is created before the tool runs and finished after,
        which is what makes the work visible while it is happening rather
        than only once it is over.
        """
        activity = self.activities.create(
            kind="tool",
            label=call.name,
            source=self.source,
            parent_id=self.parent_id,
            detail=_describe_arguments(call.arguments),
        )
        self.activities.started(activity)
        yield {
            "type": "tool_start",
            "activity": activity.id,
            "name": call.name,
            "arguments": call.arguments,
        }

        # Copied from the loop's own context rather than rebuilt field by
        # field, so that only the two per-call values differ and everything
        # else travels automatically. Rebuilding it by hand silently dropped
        # `spawn` the day delegation was added, and would drop the next
        # field added too -- the failure is invisible, because the tool just
        # finds the attribute missing and reports itself unwired.
        context = replace(self.context, activity=activity, source=self.source)
        result: ToolResult = await self.registry.invoke(
            call.name, call.arguments, context, self.scope
        )

        if result.is_error:
            self.activities.failed(activity, result.summary or "failed", result.payload)
        else:
            self.activities.completed(activity, result.summary, result.payload)

        results.append(
            {
                "type": "tool_result",
                "tool_use_id": call.id,
                "content": result.text,
                "is_error": result.is_error,
            }
        )

        yield {
            "type": "tool_end",
            "activity": activity.id,
            "name": call.name,
            "arguments": call.arguments,
            "summary": result.summary,
            "is_error": result.is_error,
        }

    def _cancel(self, call: ToolCall, results: list[dict[str, Any]]) -> dict[str, Any]:
        """Answer a tool call that was never run, because the owner stopped.

        Given an Activity of its own, created and immediately cancelled, so
        the pane shows what was dropped rather than the work quietly being
        one item shorter than the Resident said it would be.
        """
        activity = self.activities.create(
            kind="tool",
            label=call.name,
            source=self.source,
            parent_id=self.parent_id,
            detail=_describe_arguments(call.arguments),
        )
        self.activities.cancelled(activity)
        results.append(
            {
                "type": "tool_result",
                "tool_use_id": call.id,
                "content": "Not run: the owner stopped the Resident before this.",
                "is_error": True,
            }
        )
        return {
            "type": "tool_end",
            "activity": activity.id,
            "name": call.name,
            "arguments": call.arguments,
            "summary": "cancelled",
            "is_error": True,
        }

    # -- keeping what happened ------------------------------------------

    def _keep(
        self,
        record: Callable[..., Any],
        working: list[Message],
        text: str,
        calls: list[ToolCall],
    ) -> None:
        """Record one reply, and add it to what the model sees next round."""
        if not text.strip() and not calls:
            return

        blocks: list[dict[str, Any]] | None = None
        if calls:
            blocks = []
            if text.strip():
                blocks.append({"type": "text", "text": text})
            blocks.extend(
                {
                    "type": "tool_use",
                    "id": call.id,
                    "name": call.name,
                    "input": call.arguments,
                }
                for call in calls
            )

        # The prose rendering is what the interface shows and what the token
        # estimate measures; the blocks are what actually gets sent back.
        # See Store.add_message for why both are kept.
        rendered = text if text.strip() else _render_calls(calls)
        record("resident", rendered, blocks=blocks, model_label=self.label)
        working.append(Message(role="resident", content=rendered, blocks=blocks))

    def _keep_results(
        self,
        record: Callable[..., Any],
        working: list[Message],
        results: list[dict[str, Any]],
    ) -> None:
        """Record every result from one round as a single message.

        One message rather than one each, because they answer one reply and
        a window that could fit half of them would be a window that fits
        none: both wire formats reject a result whose call is missing.
        Keeping them together is what lets the fitting logic treat the whole
        exchange as the indivisible thing it is.
        """
        if not results:
            return
        rendered = "\n\n".join(
            f"{'[failed] ' if r['is_error'] else ''}{r['content']}" for r in results
        )
        record("tool", rendered, blocks=results)
        working.append(Message(role="tool", content=rendered, blocks=results))


def _describe_arguments(arguments: dict[str, Any]) -> str:
    """A tool call's arguments as one short line for the Activities panel.

    The owner wants to see *which* file is being read, not the whole
    argument object -- and a write_file's content argument could be the
    entire file.
    """
    if not arguments:
        return ""
    parts = []
    for key, value in list(arguments.items())[:3]:
        text = str(value)
        if len(text) > 60:
            text = f"{text[:57]}..."
        parts.append(f"{key}={text}")
    return ", ".join(parts)


def _render_calls(calls: list[ToolCall]) -> str:
    """What to show where a reply was tool calls and no words at all.

    Frequent with small models, which often reach straight for a tool
    without saying anything first. The conversation needs *something* on
    that row, and naming the tools is more use than an empty bubble.
    """
    return ", ".join(call.name for call in calls)
