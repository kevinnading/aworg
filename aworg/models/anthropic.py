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
    supports_tools = True

    @property
    def default_base_url(self) -> str:
        return "https://api.anthropic.com"

    def _headers(self) -> dict[str, str]:
        """The credential, the API version, and anything the profile adds."""
        return {
            **self._auth_headers(),
            **self.extra_headers,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

    async def list_models(self) -> list[str]:
        """Anthropic publishes its models, and pages them."""
        names: list[str] = []
        url = f"{self.base_url}/v1/models?limit=100"
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                while url:
                    response = await client.get(url, headers=self._headers())
                    if response.status_code >= 400:
                        raise ModelError(
                            _describe(response.status_code, response.text)
                        )
                    body = response.json()
                    names.extend(
                        item["id"] for item in body.get("data") or []
                        if isinstance(item, dict) and isinstance(item.get("id"), str)
                    )
                    after = body.get("last_id") if body.get("has_more") else None
                    url = (
                        f"{self.base_url}/v1/models?limit=100&after_id={after}"
                        if after else ""
                    )
        except httpx.RequestError as exc:
            raise ModelError(f"Could not reach {self.base_url}: {exc}") from exc
        except ValueError as exc:
            raise ModelError(f"{self.base_url} did not answer with a model list.") from exc
        return sorted(names)

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
            "messages": _wire_messages(messages),
        }
        if system:
            payload["system"] = system
        if tools:
            # MCP names the field inputSchema; this API names it
            # input_schema. Translating here is exactly what an adapter is
            # for -- nothing above this layer should know either spelling.
            payload["tools"] = [
                {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "input_schema": tool.get("inputSchema")
                    or {"type": "object", "properties": {}},
                }
                for tool in tools
            ]

        headers = self._headers()
        #: Tool calls arrive as their arguments being typed out a few
        #: characters at a time, keyed by position in the reply. Held here
        #: until the block closes, because a half-built argument object is
        #: not something anyone can be handed.
        building: dict[int, dict[str, Any]] = {}

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
                            block = event.get("content_block") or {}
                            if block.get("type") == "tool_use":
                                building[event.get("index", 0)] = {
                                    "id": block.get("id", ""),
                                    "name": block.get("name", ""),
                                    "json": "",
                                }

                        elif kind == "content_block_delta":
                            delta = event.get("delta") or {}
                            if delta.get("type") == "text_delta":
                                yield Fragment("reply", delta.get("text", ""))
                            elif delta.get("type") == "thinking_delta":
                                yield Fragment("thinking", delta.get("thinking", ""))
                            elif delta.get("type") == "input_json_delta":
                                pending = building.get(event.get("index", 0))
                                if pending is not None:
                                    pending["json"] += delta.get("partial_json", "")

                        elif kind == "content_block_stop":
                            pending = building.pop(event.get("index", 0), None)
                            if pending is not None:
                                yield Fragment(
                                    "tool_use",
                                    tool_call=ToolCall(
                                        id=pending["id"],
                                        name=pending["name"],
                                        arguments=_arguments(pending["json"]),
                                    ),
                                )

                        elif kind == "error":
                            detail = (event.get("error") or {}).get("message", "unknown error")
                            raise ModelError(detail)
        except httpx.RequestError as exc:
            raise ModelError(f"Could not reach {self.base_url}: {exc}") from exc


def _arguments(raw: str) -> dict[str, Any]:
    """The arguments a tool call was streamed with.

    A model that emitted no arguments at all sends an empty string rather
    than `{}`, and one that was cut off mid-object sends something that will
    not parse. Both become an empty dict here, because the tool layer already
    answers a missing argument by naming the schema -- which gives the model
    something to correct -- where an exception here would end the turn.
    """
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _wire_messages(messages: list[Message]) -> list[dict[str, Any]]:
    """AWORG's conversation in this API's shape.

    Two translations. AWORG's three roles collapse into the two this API
    has: a tool result is something the model is *told*, so it travels as a
    user message, which is where this API expects tool_result blocks.

    And adjacent messages of the same role are merged. Several tools
    answering one reply are separate rows in the conversation and one turn
    on the wire, and sending them separately would be several user messages
    in a row where the API expects one.
    """
    wire: list[dict[str, Any]] = []
    for message in messages:
        role = "assistant" if message.role == "resident" else "user"
        content: Any = (
            [_clean(block) for block in message.blocks]
            if message.blocks else message.content
        )

        if wire and wire[-1]["role"] == role:
            previous = wire[-1]["content"]
            if isinstance(previous, str):
                previous = [{"type": "text", "text": previous}] if previous else []
            if isinstance(content, str):
                content = [{"type": "text", "text": content}] if content else []
            wire[-1]["content"] = previous + content
        else:
            wire.append({"role": role, "content": content})
    return wire


#: Keys AWORG puts on a content block for its own interface, which are no
#: part of the API's shape. Dropped rather than tolerated: this API is strict
#: about content blocks, and a field invented here is not its problem.
OURS = ("for_owner",)


def _clean(block: dict[str, Any]) -> dict[str, Any]:
    """One block with AWORG's own annotations taken off, recursively."""
    if not isinstance(block, dict):
        return block
    out = {k: v for k, v in block.items() if k not in OURS}
    content = out.get("content")
    if isinstance(content, list):
        out["content"] = [_clean(part) for part in content]
    return out


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
