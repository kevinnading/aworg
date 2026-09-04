"""Adapter for the Anthropic Messages API."""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

from .base import Fragment, Message, ModelAdapter, ModelError, ToolCall


ANTHROPIC_VERSION = "2023-06-01"

#: Effectively no ceiling; see the payload below.
MAX_TOKENS = 64000

#: A thinking model can be silent for a long time before its first word, so a
#: single overall deadline is wrong: it cuts off work that is going fine. What
#: should fail fast is a connection that is not there, and what should fail
#: A reply is never cut off for taking too long: there is no read deadline
#: at all, because a model that thinks for ten minutes is still working and
#: the owner can stop it themselves. Only the connection is timed, so a
#: server that is not there fails immediately instead of hanging.
STREAM_TIMEOUT = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0)


class AnthropicAdapter(ModelAdapter):
    provider = "anthropic"

    @property
    def default_base_url(self) -> str:
        return "https://api.anthropic.com"

    @staticmethod
    def _wire(messages: list[Message]) -> list[dict[str, Any]]:
        """AWORG's conversation, in the shape this API expects.

        Two things make this more than a role rename. Asking for a tool is
        not a message with a field attached here -- it is content blocks
        inside the assistant's own turn, alongside whatever it said first.
        And a tool's answer is not a role of its own: it is content the
        *user* supplies, because from the model's side that answer arrives
        from outside exactly as the owner's words do.

        Results are merged into a single user turn rather than sent one after
        another. A model that asked for three things at once is owed one
        reply carrying three answers; three consecutive user turns describe a
        conversation that never happened.
        """
        wire: list[dict[str, Any]] = []
        for message in messages:
            if message.tool_call_id:
                block = {
                    "type": "tool_result",
                    "tool_use_id": message.tool_call_id,
                    "content": message.content or "(no output)",
                }
                if (
                    wire
                    and wire[-1]["role"] == "user"
                    and isinstance(wire[-1]["content"], list)
                    and wire[-1]["content"][0].get("type") == "tool_result"
                ):
                    wire[-1]["content"].append(block)
                else:
                    wire.append({"role": "user", "content": [block]})
                continue

            if message.tool_calls:
                blocks: list[dict[str, Any]] = []
                if message.content.strip():
                    blocks.append({"type": "text", "text": message.content})
                blocks.extend(
                    {
                        "type": "tool_use",
                        "id": call.id,
                        "name": call.name,
                        "input": call.arguments or {},
                    }
                    for call in message.tool_calls
                )
                wire.append({"role": "assistant", "content": blocks})
                continue

            # An empty turn is dropped rather than sent. The API refuses one,
            # and that refusal would reach the owner as their whole
            # conversation being broken by a message that said nothing.
            if not message.content.strip():
                continue
            wire.append({
                "role": "user" if message.role == "owner" else "assistant",
                "content": message.content,
            })
        return wire

    @staticmethod
    def _tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        """AWORG's tool descriptions, in this API's shape.

        The same three facts as everywhere else, with the schema under a
        different name. That this is the whole of the difference is the
        argument for having the layer at all.
        """
        if not tools:
            return None
        return [
            {
                "name": tool["name"],
                "description": tool["description"],
                "input_schema": tool["parameters"],
            }
            for tool in tools
        ]

    async def stream(
        self,
        messages: list[Message],
        system: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[Fragment]:
        payload: dict[str, Any] = {
            "model": self.model,
            # The API requires a ceiling, so this is set past what any current
            # model will produce rather than to a number that would cut a
            # reply short. A provider that rejects it says so plainly, which
            # is a better failure than a reply that stops mid-sentence.
            "max_tokens": MAX_TOKENS,
            "stream": True,
            "messages": self._wire(messages),
        }
        if system:
            payload["system"] = system
        described = self._tools(tools)
        if described:
            payload["tools"] = described

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=STREAM_TIMEOUT) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/v1/messages",
                    json=payload,
                    headers=headers,
                ) as response:
                    if response.status_code >= 400:
                        body = (await response.aread()).decode("utf-8", "replace")
                        raise ModelError(_describe(response.status_code, body))
                    # Arguments accumulate per content block, keyed by the
                    # index the API gives it, and become a call when that
                    # block closes.
                    pending: dict[int, dict[str, str]] = {}
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        chunk = line[5:].strip()
                        if not chunk:
                            continue
                        try:
                            event = json.loads(chunk)
                        except json.JSONDecodeError:
                            continue
                        kind = event.get("type")
                        if kind == "content_block_start":
                            # A tool call opens a block of its own, named and
                            # identified up front; only its arguments arrive
                            # piecemeal after this.
                            block = event.get("content_block") or {}
                            if block.get("type") == "tool_use":
                                pending[event.get("index", 0)] = {
                                    "id": block.get("id", ""),
                                    "name": block.get("name", ""),
                                    "arguments": "",
                                }
                        elif kind == "content_block_delta":
                            delta = event.get("delta") or {}
                            if delta.get("type") == "text_delta":
                                yield Fragment("reply", delta.get("text", ""))
                            elif delta.get("type") == "thinking_delta":
                                yield Fragment("thinking", delta.get("thinking", ""))
                            elif delta.get("type") == "input_json_delta":
                                slot = pending.get(event.get("index", 0))
                                if slot is not None:
                                    slot["arguments"] += delta.get("partial_json", "")
                        elif kind == "content_block_stop":
                            # The block is closed, so the call is whole.
                            slot = pending.pop(event.get("index", 0), None)
                            if slot and slot["name"]:
                                yield Fragment("tool_call", call=_assemble(slot))
                        elif kind == "error":
                            detail = (event.get("error") or {}).get("message", "unknown error")
                            raise ModelError(detail)
        except httpx.RequestError as exc:
            raise ModelError(f"Could not reach {self.base_url}: {exc}") from exc


def _assemble(slot: dict[str, str]) -> ToolCall:
    """Turn an accumulated tool_use block into a call.

    Arguments arrive as a JSON string across many deltas and can end badly.
    The commonest case is the empty string, which is simply what a tool
    taking no arguments sends. Neither is worth ending a turn over: the tool
    says what was wrong with what it got, and the model tries again.
    """
    try:
        arguments = json.loads(slot["arguments"] or "{}")
        if not isinstance(arguments, dict):
            arguments = {"value": arguments}
    except json.JSONDecodeError:
        arguments = {}
    return ToolCall(
        id=slot["id"] or f"call_{slot['name']}",
        name=slot["name"],
        arguments=arguments,
    )


def _describe(status: int, body: str) -> str:
    """Turn a provider error into something an owner can act on."""
    try:
        detail = (json.loads(body).get("error") or {}).get("message")
    except (json.JSONDecodeError, AttributeError):
        detail = None
    # Shown in full: a provider error cut in half is a provider error the
    # owner cannot act on.
    detail = detail or body.strip() or "no detail provided"

    if status == 401:
        return f"Authentication failed - check the credential. ({detail})"
    if status == 404:
        return f"Model not found - check the model identifier. ({detail})"
    if status == 429:
        return f"Rate limited by the provider. ({detail})"
    return f"Provider returned {status}: {detail}"
