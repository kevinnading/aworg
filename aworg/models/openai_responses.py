"""Adapter for OpenAI's Responses API.

A third wire format rather than a branch inside the second one, which is what
providers.py asks for in its own docstring: the moment a provider needs its
own behaviour, that belongs behind a field in the profile rather than in a
growing `if provider ==` underneath.

The chat-completions adapter stays exactly as it is, and keeps every other
provider. This one is for OpenAI proper, where Responses is the API the newer
models are built around: reasoning effort, and the reasoning families that are
only fully addressable through it.

Four differences do the work, and everything else follows from them.

    instructions      the system prompt is a field, not a message
    input             a list of items, not of messages
    function_call     a tool request is its own item, not an attachment to
                      an assistant message
    tools             flat -- name and parameters at the top of the
                      descriptor, where completions nests them under
                      "function"

The last is the one that fails quietly if you get it wrong: a nested
descriptor is accepted as a tool with no name, and the model simply never
calls anything.

**State stays here.** `store` is sent false and `previous_response_id` is
never used, so OpenAI holds nothing between turns and AWORG sends the whole
conversation every time. That is the same bargain the other adapters make and
it is what keeps the Resident's memory a thing the owner possesses rather
than a handle into somebody's server. The cost is noted at `_input`.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, AsyncIterator

import httpx

from .base import (
    BLIND, Fragment, Message, ModelAdapter, ModelError, ToolCall,
    picture_omitted, refused_a_picture,
)


#: The same reasoning as the completions adapter: a model that thinks for ten
#: minutes is working, not hung, so only the connection is timed.
STREAM_TIMEOUT = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0)

#: Model families that accept a `reasoning` block. Sending one to a model
#: that does not is a 400, so it cannot simply always be sent.
#:
#: A name check, and an unhappy one -- but the API offers no way to ask a
#: model what it supports, and the alternatives are worse. Always sending it
#: breaks every non-reasoning model; never sending it throws away the control
#: this API exists to expose. A name that is not listed here gets no
#: reasoning block, which is the safe direction: the model reasons however it
#: defaults to, and nothing is refused.
REASONING_FAMILIES = ("o1", "o3", "o4", "gpt-5")

#: Names inside those families that do not reason after all. `gpt-5-chat` is
#: the plain chat model of the gpt-5 generation and refuses a reasoning block
#: exactly as gpt-4o would, so the family check alone would 400 on it.
NOT_REASONING = ("-chat",)

#: What the owner's reasoning setting means here.
#:
#: "off" cannot mean off -- a reasoning model reasons, and asking it not to
#: is asking it to be a different model. It means as little as the API will
#: accept, which is what the setting is actually for: the owner is buying
#: back latency, not changing the answer.
EFFORT = {"off": "minimal", "low": "low", "high": "high"}


class OpenAIResponsesAdapter(ModelAdapter):
    """Translates between AWORG and OpenAI's Responses API."""

    provider = "openai"
    supports_tools = True

    #: Whether to ask for reasoning summaries. Turned off for good on the
    #: first request that is refused for wanting them; see `_reasoning`.
    summaries = True

    @property
    def default_base_url(self) -> str:
        return "https://api.openai.com/v1"

    # -- the conversation, in this API's shape ---------------------------

    def _input(self, messages: list[Message]) -> list[dict[str, Any]]:
        """AWORG's conversation as a list of input items.

        Where completions gives every tool result a message with role "tool",
        this format has no tool role at all: a request and its result are
        both items in one flat list, paired by `call_id`. So an assistant
        message that asked for three tools becomes one message item and three
        function_call items, and the stored message holding their results
        becomes three function_call_output items.

        Reasoning items are not carried back. With `store` false they would
        have to be round-tripped as encrypted content, and OpenAI's own
        guidance is that passing them improves a reasoning model's work
        across tool calls rather than being required for it. That is a real
        cost and it is the one this adapter knowingly pays for statelessness;
        the way to buy it back is `include: ["reasoning.encrypted_content"]`
        and replaying the items, which is worth doing when there is a
        measurement saying it matters.
        """
        items: list[dict[str, Any]] = []

        for message in messages:
            if not message.blocks:
                items.append(
                    {
                        # Not the Resident means the Resident is being told,
                        # so it goes as user. See the same note in
                        # openai_compatible.py: the inverse test made any
                        # role added later arrive as the Resident's own words.
                        "role": "assistant" if message.role == "resident" else "user",
                        "content": message.content,
                    }
                )
                continue

            if message.role == "tool":
                # `output` is a string here, so a picture follows as a user
                # message -- the one place this API does take an image.
                pictures: list[dict[str, Any]] = []
                for block in message.blocks:
                    if block.get("type") != "tool_result":
                        continue
                    items.append(
                        {
                            "type": "function_call_output",
                            "call_id": block.get("tool_use_id", ""),
                            "output": _as_text(block.get("content")),
                        }
                    )
                    pictures.extend(_images(block.get("content")))
                if pictures:
                    items.append({
                        "role": "user",
                        "content": [
                            {"type": "input_text",
                             "text": "The picture that tool returned:"},
                            *[
                                {"type": "input_image",
                                 "image_url": _data_url(picture)}
                                for picture in pictures
                            ],
                        ],
                    })
                continue

            text = "".join(
                block.get("text", "")
                for block in message.blocks
                if block.get("type") == "text"
            )
            if text:
                items.append({"role": "assistant", "content": text})
            for block in message.blocks:
                if block.get("type") != "tool_use":
                    continue
                items.append(
                    {
                        "type": "function_call",
                        "call_id": block.get("id", ""),
                        "name": block.get("name", ""),
                        # A JSON string here, an object in MCP. The same
                        # translation the completions adapter makes.
                        "arguments": json.dumps(block.get("input") or {}),
                    }
                )

        return items

    def _tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """MCP descriptors as this API wants them: flat.

        The difference from completions is one level of nesting and it is
        worth stating plainly, because getting it wrong does not raise. A
        descriptor with `function: {name: ...}` is accepted, read as a tool
        whose name is absent, and the model then never calls anything -- which
        looks exactly like a model that has decided not to.
        """
        return [
            {
                "type": "function",
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("inputSchema")
                or {"type": "object", "properties": {}},
            }
            for tool in tools
        ]

    def _reasoning(self) -> dict[str, Any] | None:
        """The reasoning block, when this model will accept one."""
        name = (self.model or "").lower()
        if any(mark in name for mark in NOT_REASONING):
            return None
        if not any(name.startswith(f) or f in name for f in REASONING_FAMILIES):
            return None
        effort = EFFORT.get(self.reasoning)
        block: dict[str, Any] = {"effort": effort} if effort else {}
        # A summary of the thinking, so the interface can show the model is
        # working rather than showing nothing for thirty seconds -- the
        # problem the completions adapter solved by reading
        # `reasoning_content`, which this API does not have.
        #
        # Asked for, not assumed. Streaming reasoning summaries requires a
        # verified organisation, and an unverified one is refused the whole
        # request rather than just the summary. So the first refusal turns
        # this off for the life of the connection and the request is retried
        # without it: an owner who has not verified gets a working Resident
        # that does not narrate, rather than a Resident that will not answer.
        if self.summaries:
            block["summary"] = "auto"
        return block

    # -- asking -----------------------------------------------------------

    async def list_models(self) -> list[str]:
        """`GET /models`, the same call the completions adapter makes."""
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.get(
                    f"{self.base_url}/models",
                    headers={**self._auth_headers(), **self.extra_headers},
                )
                if response.status_code >= 400:
                    raise ModelError(_describe(response.status_code, response.text))
                data = response.json().get("data")
                if not isinstance(data, list):
                    return []
                return sorted(
                    item["id"] for item in data
                    if isinstance(item, dict) and isinstance(item.get("id"), str)
                )
        except httpx.RequestError as exc:
            raise ModelError(f"Could not reach {self.base_url}: {exc}") from exc
        except ValueError as exc:
            raise ModelError(f"{self.base_url} did not answer with a model list.") from exc

    async def stream(
        self,
        messages: list[Message],
        system: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[Fragment]:
        items = self._input(messages)
        # Asked before the first attempt rather than only after a failure.
        # Once a connection has refused a picture there is no reason to send
        # it another and spend a round trip learning the same thing twice.
        if self.connection_id in BLIND:
            items = _without_pictures(items)

        payload: dict[str, Any] = {
            "model": self.model,
            "input": items,
            "stream": True,
            # AWORG keeps the conversation. Nothing is left on OpenAI's
            # servers between turns, which is the same bargain every other
            # adapter makes and the reason the whole history is sent each
            # time rather than a previous_response_id.
            "store": False,
        }
        if system:
            payload["instructions"] = system
        if tools:
            payload["tools"] = self._tools(tools)
        reasoning = self._reasoning()
        if reasoning:
            payload["reasoning"] = reasoning

        headers = {
            **self._auth_headers(),
            **self.extra_headers,
            "Content-Type": "application/json",
        }

        # Stay inside the allowance before asking, rather than finding out
        # by being refused halfway through a turn.
        waited = await self.wait_for_budget(payload)
        if waited:
            yield Fragment(
                "waiting",
                f"Staying inside this connection's rate limit -- {waited:.0f}s.",
            )

        try:
            for attempt in range(RATE_LIMIT_TRIES):
                async with httpx.AsyncClient(timeout=STREAM_TIMEOUT) as client:
                    async with client.stream(
                        "POST", f"{self.base_url}/responses", json=payload,
                        headers=headers,
                    ) as response:
                        if response.status_code == 429 and attempt < RATE_LIMIT_TRIES - 1:
                            # Expected rather than exceptional. The budget is
                            # an estimate against a number the provider counts
                            # its own way, and a key may be shared -- so this
                            # is waited out and retried instead of ending the
                            # turn. Ending it is what left an owner with a
                            # conversation that stopped after a tool result
                            # and no explanation.
                            body = (await response.aread()).decode("utf-8", "replace")
                            pause = _retry_after(response, body)
                            yield Fragment(
                                "waiting",
                                f"Rate limited by OpenAI -- waiting {pause:.0f}s "
                                "and trying again.",
                            )
                            await asyncio.sleep(pause)
                            continue
                        async for fragment in self._read(response, payload,
                                                         messages, system, tools):
                            yield fragment
                        return
        except httpx.RequestError as exc:
            raise ModelError(f"Could not reach {self.base_url}: {exc}") from exc

    async def _read(
        self,
        response: Any,
        payload: dict[str, Any],
        messages: list[Message],
        system: str,
        tools: list[dict[str, Any]] | None,
    ) -> AsyncIterator[Fragment]:
        """Turn one streamed response into fragments.

        Split out from `stream` so that the retry above can wrap the request
        without the parsing being indented inside two more loops.
        """
        building: dict[str, dict[str, str]] = {}
        cut_off = False

        # What the provider says its limits actually are, which beats the
        # default this connection started with. Read before anything else,
        # so it is adopted even on a response that turns out to be an error.
        self.budget.observe(response.headers)

        if response.status_code >= 400:
            body = (await response.aread()).decode("utf-8", "replace")
            if self.summaries and _wants_verification(body):
                # Asked for reasoning summaries and this
                # organisation is not allowed them. The refusal is
                # of the whole request, not of the summary, so
                # without this an unverified owner has a Resident
                # that cannot answer at all. Give up the narration
                # for the life of the connection and ask again.
                self.summaries = False
                payload.pop("reasoning", None)
                again = self._reasoning()
                if again:
                    payload["reasoning"] = again
                async for fragment in self.stream(messages, system, tools):
                    yield fragment
                return
            if refused_a_picture(response.status_code, body) and any(
                isinstance(item.get("content"), list)
                and any(part.get("type") == "input_image"
                        for part in item["content"])
                for item in payload["input"]
            ):
                # Written down against the connection, so the rest of this
                # conversation and every later one skips the pictures rather
                # than dying on them. Retried the same way the verification
                # refusal above is: give the thing up for this connection and
                # ask again.
                if self.connection_id:
                    BLIND.add(self.connection_id)
                async for fragment in self.stream(messages, system, tools):
                    yield fragment
                return
            raise ModelError(_describe(response.status_code, body))

        async for line in response.aiter_lines():
            # Only the data lines are read. The stream also
            # carries `event:` lines naming the same thing, and
            # reading one source rather than pairing two is both
            # shorter and harder to get out of step.
            if not line.startswith("data:"):
                continue
            chunk = line[5:].strip()
            if not chunk or chunk == "[DONE]":
                continue
            try:
                event = json.loads(chunk)
            except json.JSONDecodeError:
                continue

            kind = event.get("type") or ""

            if kind == "response.output_text.delta":
                text = event.get("delta")
                if text:
                    yield Fragment("reply", text)

            elif kind in (
                "response.reasoning_summary_text.delta",
                # Older naming, still sent by some deployments.
                "response.reasoning_summary.delta",
            ):
                text = event.get("delta")
                if text:
                    yield Fragment("thinking", text)

            elif kind == "response.output_item.added":
                item = event.get("item") or {}
                if item.get("type") == "function_call":
                    building[item.get("id") or ""] = {
                        # call_id is what a result must come back
                        # with, and it is a different value from
                        # the item's own id. Mixing them up
                        # produces a result the API rejects as
                        # matching no call.
                        "call_id": item.get("call_id", ""),
                        "name": item.get("name", ""),
                        "json": "",
                    }

            elif kind == "response.function_call_arguments.delta":
                slot = building.get(event.get("item_id") or "")
                if slot is not None and event.get("delta"):
                    slot["json"] += event["delta"]

            elif kind == "response.function_call_arguments.done":
                slot = building.get(event.get("item_id") or "")
                # The complete arguments, if the API chose to send
                # them whole. Preferred over what was accumulated,
                # because a dropped delta would otherwise leave a
                # fragment that will not parse.
                if slot is not None and isinstance(event.get("arguments"), str):
                    slot["json"] = event["arguments"]

            elif kind == "response.incomplete":
                cut_off = True

            elif kind == "response.completed":
                body = event.get("response") or {}
                if body.get("status") == "incomplete":
                    cut_off = True

            elif kind in ("error", "response.failed"):
                detail = (
                    (event.get("error") or {}).get("message")
                    or ((event.get("response") or {}).get("error") or {})
                    .get("message")
                    or "the provider reported an error mid-reply"
                )
                raise ModelError(f"OpenAI: {detail}")

        for slot in building.values():
            if not slot["name"]:
                continue
            parsed = _arguments(slot["json"])
            yield Fragment(
                "tool_use",
                tool_call=ToolCall(
                    id=slot["call_id"] or f"call_{slot['name']}",
                    name=slot["name"],
                    arguments=parsed or {},
                    # Severed either way: arguments that will not
                    # parse, or the API saying it ran out of room
                    # with a call open.
                    truncated=(parsed is None)
                    or (cut_off and bool(slot["json"])),
                ),
            )


#: How OpenAI phrases the refusal that is worth retrying rather than showing.
#: Matched on the subject rather than the sentence, because the wording has
#: changed before and a message that drifts should cost the narration rather
#: than the whole reply.
VERIFICATION_MARKS = ("must be verified", "organization must be verified",
                      "unsupported_value", "reasoning.summary")


def _wants_verification(body: str) -> bool:
    """Whether this refusal was about reasoning summaries specifically."""
    lowered = body.lower()
    return "summary" in lowered and any(
        mark in lowered for mark in VERIFICATION_MARKS
    )


#: How long to wait after a refusal that did not say. Providers usually send
#: retry-after; this is for the ones that do not.
DEFAULT_BACKOFF = 20.0

#: How many times to wait out a rate limit before giving up on the turn.
#: Three is enough to ride out a minute-long window twice over, and few
#: enough that a genuinely exhausted quota still ends rather than hanging.
RATE_LIMIT_TRIES = 3


def _retry_after(response: Any, body: str) -> float:
    """How long the provider asked us to wait, or a sensible guess.

    Read from the header where there is one. The message sometimes carries
    the number too -- "try again in 12.4s" -- and that is worth parsing,
    because waiting the guess when the provider told us the answer is time
    the owner spends watching nothing.
    """
    header = ""
    try:
        header = response.headers.get("retry-after", "") or ""
    except Exception:                                      # noqa: BLE001
        header = ""
    if header.strip():
        try:
            return max(1.0, float(header.strip()))
        except ValueError:
            pass
    found = re.search(r"try again in ([0-9.]+)\s*(ms|s)", body, re.I)
    if found:
        value = float(found.group(1))
        return max(1.0, value / 1000 if found.group(2).lower() == "ms" else value)
    return DEFAULT_BACKOFF


def _describe(status: int, body: str) -> str:
    """A provider error the owner can act on."""
    try:
        detail = (json.loads(body).get("error") or {}).get("message")
    except (json.JSONDecodeError, AttributeError):
        detail = None
    detail = detail or body.strip() or "no detail provided"

    if status == 401:
        return f"Authentication failed - check the credential. ({detail})"
    if status == 404:
        return (
            "Not found - check the model identifier and endpoint. This "
            "connection speaks OpenAI's Responses API; a gateway that only "
            f"offers /chat/completions needs the OpenAI-compatible provider. ({detail})"
        )
    if status == 429:
        return f"Rate limited by the provider. ({detail})"
    return f"Provider returned {status}: {detail}"


def _arguments(raw: str) -> dict[str, Any] | None:
    """The arguments a call was streamed with, or None if they were cut.

    The same distinction the completions adapter draws, and it matters for
    the same reason: an empty dict is a model that sent no arguments, while a
    fragment that will not parse is a model that was interrupted. Answering
    the second as though it were the first produces advice about the schema
    and a model that sends the identical call again.
    """
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else {}


def _images(content: Any) -> list[dict[str, Any]]:
    """The image blocks in a tool result, if it carries any."""
    if not isinstance(content, list):
        return []
    return [
        part for part in content
        if isinstance(part, dict) and part.get("type") == "image"
        and (part.get("source") or {}).get("data")
    ]


def _without_pictures(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The same input with the pixels replaced by a sentence.

    See models/base.py for BLIND and why this exists. This API's picture
    part is `input_image`, so the stripping lives with the wire format while
    the memory of which connection is blind is shared.
    """
    out: list[dict[str, Any]] = []
    for item in items:
        content = item.get("content")
        if not isinstance(content, list):
            out.append(item)
            continue
        kept = [part for part in content if part.get("type") != "input_image"]
        dropped = len(content) - len(kept)
        if not dropped:
            out.append(item)
            continue
        kept.append({"type": "input_text", "text": picture_omitted(dropped)})
        out.append({**item, "content": kept})
    return out


def _data_url(image: dict[str, Any]) -> str:
    source = image.get("source") or {}
    return (
        f"data:{source.get('media_type', 'image/png')};base64,"
        f"{source.get('data', '')}"
    )


def _as_text(content: Any) -> str:
    """A tool result as a plain string, which is all `output` accepts."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    return "" if content is None else str(content)
