"""Adapter for OpenAI-style chat completion endpoints.

Deliberately not called "the OpenAI adapter". This shape has become a de facto
interface, and one adapter covers OpenAI itself, most third-party gateways, and
local model servers running on the owner's own hardware. Supporting it from the
first milestone is what makes model agnosticism a fact rather than a claim: an
owner can point their Resident at a model running on their own machine without
AWORG needing to know anything about it.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, AsyncIterator

import httpx

from .base import Fragment, Message, ModelAdapter, ModelError, ToolCall


#: A thinking model can be silent for a long time before its first word, so a
#: single overall deadline is wrong: it cuts off work that is going fine. What
#: should fail fast is a connection that is not there, and what should fail
#: A reply is never cut off for taking too long: there is no read deadline
#: at all, because a model that thinks for ten minutes is still working and
#: the owner can stop it themselves. Only the connection is timed, so a
#: server that is not there fails immediately instead of hanging.
STREAM_TIMEOUT = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0)


#: Reasoning models mark their thinking with these. Servers are supposed to
#: strip them and deliver the thinking separately, and mostly they do -- but
#: not always, and a stray tag or a duplicated answer then ends up saved as
#: something the Resident said.
THINK_OPEN = "<think>"
THINK_CLOSE = "</think>"
_LONGEST_TAG = max(len(THINK_OPEN), len(THINK_CLOSE))


class _ThinkSplitter:
    """Separates thinking from answer within a content stream.

    The server is trusted first: whatever it delivers as reasoning is
    reasoning. This exists for what leaks through anyway, which is not
    hypothetical -- the same model on the same server answered "what is 2+2"
    with `Four.
</think>

Four.` in its content, having put half its
    thinking in the answer.

    Two rules. Text between the tags is thinking. And a closing tag with no
    opening one means everything before it was thinking that escaped, so it
    is reclassified rather than kept -- which removes the duplicated answer
    along with the tag.

    That second rule needs a look ahead: whether the opening words are an
    answer or escaped thinking is only knowable once a closing tag either
    arrives or does not. So the first few hundred characters of answer are
    held back until it is settled. After that everything streams as it
    comes, because a stray close tag belongs at the boundary and not in the
    middle of a sentence.
    """

    #: How much answer to hold while waiting to see a stray closing tag.
    #:
    #: This is a trade against streaming, so it is kept small. Escaped
    #: thinking is followed by its closing tag almost immediately -- the case
    #: this exists for had six characters before it -- while holding a long
    #: prefix would mean the opening sentence of every reply arriving in one
    #: lump. Sixty-four characters is about a short phrase: enough to catch
    #: the leak, little enough that the reply still visibly types itself.
    HOLD = 64

    def __init__(self) -> None:
        self.buffer = ""      # raw text that may still contain a partial tag
        self.held = ""        # answer withheld until the leak question settles
        self.thinking = False
        self.settled = False

    def feed(self, text: str) -> list[tuple[str, str]]:
        self.buffer += text
        out: list[tuple[str, str]] = []

        while self.buffer:
            if self.thinking:
                index = self.buffer.find(THINK_CLOSE)
                if index == -1:
                    break
                before, self.buffer = self.buffer[:index], self.buffer[index + len(THINK_CLOSE):]
                if before:
                    out.append(("thinking", before))
                self.thinking = False
                self.settled = True
                continue

            opens = self.buffer.find(THINK_OPEN)
            closes = self.buffer.find(THINK_CLOSE)
            if opens == -1 and closes == -1:
                break

            if closes != -1 and (opens == -1 or closes < opens):
                # A close with no open. Everything before it -- including
                # anything being held -- was thinking that escaped.
                before, self.buffer = self.buffer[:closes], self.buffer[closes + len(THINK_CLOSE):]
                escaped = self.held + before
                self.held = ""
                self.settled = True
                if escaped:
                    out.append(("thinking", escaped))
                continue

            before, self.buffer = self.buffer[:opens], self.buffer[opens + len(THINK_OPEN):]
            out.extend(self._answer(before))
            self.thinking = True

        keep = _partial_tail(self.buffer, THINK_OPEN, THINK_CLOSE)
        ready = self.buffer[:len(self.buffer) - keep] if keep else self.buffer
        self.buffer = self.buffer[len(self.buffer) - keep:] if keep else ""
        if ready:
            if self.thinking:
                out.append(("thinking", ready))
            else:
                out.extend(self._answer(ready))
        return out

    def _answer(self, text: str) -> list[tuple[str, str]]:
        if not text:
            return []
        if self.settled:
            return [("reply", text)]
        self.held += text
        if len(self.held) < self.HOLD:
            return []          # still waiting to see whether a close follows
        self.settled = True
        out, self.held = [("reply", self.held)], ""
        return out

    def drain(self) -> list[tuple[str, str]]:
        """The stream ended. Anything held was an answer after all."""
        left, self.buffer = self.buffer, ""
        out: list[tuple[str, str]] = []
        if self.thinking:
            if self.held:
                out.append(("thinking", self.held))
            if left:
                out.append(("thinking", left))
        else:
            tail = self.held + left
            if tail:
                out.append(("reply", tail))
        self.held = ""
        self.settled = True
        return out


def _partial_tail(buffer: str, *markers: str) -> int:
    """How many trailing characters might be the start of a tag."""
    for size in range(min(_LONGEST_TAG - 1, len(buffer)), 0, -1):
        tail = buffer[-size:]
        if any(m.startswith(tail) for m in markers):
            return size
    return 0


class OpenAICompatibleAdapter(ModelAdapter):
    provider = "openai-compatible"
    supports_tools = True

    @property
    def default_base_url(self) -> str:
        return "https://api.openai.com/v1"

    def _wire(self, messages: list[Message], system: str) -> list[dict[str, Any]]:
        """AWORG's conversation in this API's shape.

        Where the Anthropic format carries tool results as blocks inside a
        user message, this one gives every result a message of its own with
        role "tool". So one stored message holding three results becomes
        three messages here -- the two formats disagree about shape, and
        reconciling that is the whole job of an adapter.
        """
        wire: list[dict[str, Any]] = []
        if system:
            wire.append({"role": "system", "content": system})

        for message in messages:
            if not message.blocks:
                wire.append(
                    {
                        # Everything that is not the Resident is something
                        # the Resident is told, so it travels as a user
                        # message. Written the other way round -- user only
                        # for "owner" -- any role added later would arrive
                        # as words the Resident supposedly said, which is
                        # the worst possible way for a new role to fail.
                        "role": "assistant" if message.role == "resident" else "user",
                        "content": message.content,
                    }
                )
                continue

            if message.role == "tool":
                # Images cannot ride in a tool message here -- this API takes
                # a string and nothing else -- so they follow as a user
                # message, which is where it does accept them.
                pictures: list[dict[str, Any]] = []
                for block in message.blocks:
                    if block.get("type") != "tool_result":
                        continue
                    wire.append(
                        {
                            "role": "tool",
                            "tool_call_id": block.get("tool_use_id", ""),
                            "content": _as_text(block.get("content")),
                        }
                    )
                    pictures.extend(_images(block.get("content")))
                if pictures:
                    wire.append({
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "The picture that tool returned:"},
                            *[
                                {"type": "image_url",
                                 "image_url": {"url": _data_url(picture)}}
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
            calls = [
                {
                    "id": block.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        # This API wants the arguments as a JSON string,
                        # where the other wants an object.
                        "arguments": json.dumps(block.get("input") or {}),
                    },
                }
                for block in message.blocks
                if block.get("type") == "tool_use"
            ]
            entry: dict[str, Any] = {"role": "assistant", "content": text or None}
            if calls:
                entry["tool_calls"] = calls
            wire.append(entry)

        return wire

    async def list_models(self) -> list[str]:
        """`GET /models`, which nearly everything speaking this API offers."""
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
                names = [
                    item.get("id") for item in data
                    if isinstance(item, dict) and isinstance(item.get("id"), str)
                ]
                return sorted(names)
        except httpx.RequestError as exc:
            raise ModelError(f"Could not reach {self.base_url}: {exc}") from exc
        except ValueError as exc:
            raise ModelError(f"{self.base_url} did not answer with a model list.") from exc

    async def count_tokens(self, messages: list[Message], system: str) -> int | None:
        """Exact, on llama.cpp: render the chat template, then tokenize it.

        Two calls rather than one because tokenizing the raw text misses the
        template's own tokens -- a few per message, which is a few hundred
        over a long conversation. Anything that is not llama.cpp answers
        neither endpoint and gets None.
        """
        root = self.base_url[:-3] if self.base_url.endswith("/v1") else self.base_url
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                rendered = await client.post(
                    f"{root}/apply-template", json={"messages": self._wire(messages, system)}
                )
                if rendered.status_code != 200:
                    return None
                prompt = rendered.json().get("prompt")
                if not isinstance(prompt, str):
                    return None
                counted = await client.post(f"{root}/tokenize", json={"content": prompt})
                if counted.status_code != 200:
                    return None
                tokens = counted.json().get("tokens")
                return len(tokens) if isinstance(tokens, list) else None
        except (httpx.RequestError, ValueError):
            return None

    async def detect_context(self) -> int | None:
        """llama.cpp publishes its window at /props, beside the /v1 API.

        Gateways and OpenAI itself have no such endpoint and answer with a
        404 or an HTML page, both of which mean "unknown" here, not "broken".
        """
        root = self.base_url[:-3] if self.base_url.endswith("/v1") else self.base_url
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{root}/props")
                if response.status_code != 200:
                    return None
                settings = response.json().get("default_generation_settings") or {}
                n_ctx = settings.get("n_ctx")
                return int(n_ctx) if isinstance(n_ctx, int) and n_ctx > 0 else None
        except (httpx.RequestError, ValueError):
            return None

    async def stream(
        self,
        messages: list[Message],
        system: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[Fragment]:
        wire = self._wire(messages, system)

        payload: dict[str, Any] = {"model": self.model, "messages": wire, "stream": True}
        if tools:
            # MCP's inputSchema becomes this API's function.parameters. Same
            # JSON Schema, different place to put it.
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "parameters": tool.get("inputSchema")
                        or {"type": "object", "properties": {}},
                    },
                }
                for tool in tools
            ]
        if self.reasoning == "off":
            # The convention llama.cpp and most gateways accept. A server that
            # does not understand it ignores it, which is the right failure:
            # the reply is slower than asked for, not absent.
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        headers = {
            **self._auth_headers(),
            **self.extra_headers,
            "Content-Type": "application/json",
        }

        splitter = _ThinkSplitter()
        #: Why the model stopped. "length" means it was cut off rather than
        #: finished, which is otherwise invisible -- the stream simply ends,
        #: and a half-written tool call looks like a badly-formed one.
        stopped_for: str | None = None
        #: Tool calls accumulate by index across many chunks. Unlike the
        #: Anthropic stream there is no per-call "stop" event, so these are
        #: held until the stream ends and flushed together.
        building: dict[int, dict[str, str]] = {}

        waited = await self.wait_for_budget(payload)
        if waited:
            yield Fragment(
                "waiting",
                f"Staying inside this connection's rate limit -- {waited:.0f}s.",
            )

        try:
            async with httpx.AsyncClient(timeout=STREAM_TIMEOUT) as client:
                for attempt in range(RATE_LIMIT_TRIES):
                    async with client.stream(
                        "POST",
                        f"{self.base_url}/chat/completions",
                        json=payload,
                        headers=headers,
                    ) as response:
                        # The provider's own figures, which are better than
                        # the default this connection started with.
                        self.budget.observe(response.headers)
                        if response.status_code == 429 and attempt < RATE_LIMIT_TRIES - 1:
                            # Waited out rather than raised. See the same guard in
                            # openai_responses.py for why a rate limit must not be
                            # allowed to end a turn.
                            body = (await response.aread()).decode("utf-8", "replace")
                            pause = _retry_after(response, body)
                            yield Fragment(
                                "waiting",
                                f"Rate limited -- waiting {pause:.0f}s and trying again.",
                            )
                            await asyncio.sleep(pause)
                            continue
                        if response.status_code >= 400:
                            body = (await response.aread()).decode("utf-8", "replace")
                            raise ModelError(_describe(response.status_code, body))
                        async for line in response.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            chunk = line[5:].strip()
                            if not chunk or chunk == "[DONE]":
                                continue
                            try:
                                event = json.loads(chunk)
                            except json.JSONDecodeError:
                                continue
                            choices = event.get("choices") or []
                            if not choices:
                                continue
                            if choices[0].get("finish_reason"):
                                stopped_for = choices[0]["finish_reason"]
                            delta = choices[0].get("delta") or {}
                            # Reasoning models send their thinking down the same
                            # stream under a different key. Reading only `content`
                            # means yielding nothing at all while the model works:
                            # a 9B answering "what is 2+2" sent 260 reasoning
                            # chunks before the first content chunk, and everything
                            # above here saw silence for all of them.
                            thinking = delta.get("reasoning_content")
                            if thinking:
                                yield Fragment("thinking", thinking)
                            text = delta.get("content")
                            if text:
                                for kind, part in splitter.feed(text):
                                    yield Fragment(kind, part)

                            for call in delta.get("tool_calls") or []:
                                slot = building.setdefault(
                                    call.get("index", 0), {"id": "", "name": "", "json": ""}
                                )
                                # The id and name arrive once, at the start; the
                                # arguments arrive in pieces after. Guarding each
                                # rather than overwriting stops a later empty
                                # chunk from erasing what was already collected.
                                if call.get("id"):
                                    slot["id"] = call["id"]
                                function = call.get("function") or {}
                                if function.get("name"):
                                    slot["name"] = function["name"]
                                if function.get("arguments"):
                                    slot["json"] += function["arguments"]

                        for kind, part in splitter.drain():
                            yield Fragment(kind, part)

                        for _, slot in sorted(building.items()):
                            if not slot["name"]:
                                continue
                            parsed = _arguments(slot["json"])
                            # Arguments that were sent but will not parse mean the
                            # reply was severed mid-object. So does the server
                            # saying it stopped for length while a call was open.
                            cut = (parsed is None) or (
                                stopped_for == "length" and bool(slot["json"])
                            )
                            yield Fragment(
                                "tool_use",
                                tool_call=ToolCall(
                                    id=slot["id"] or f"call_{slot['name']}",
                                    name=slot["name"],
                                    arguments=parsed or {},
                                    truncated=cut,
                                ),
                            )
                        # One good pass is the whole job. Without this the retry
                        # loop would send the same request again.
                        return
        except httpx.RequestError as exc:
            raise ModelError(f"Could not reach {self.base_url}: {exc}") from exc


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
        return f"Not found - check the model identifier and endpoint. ({detail})"
    if status == 429:
        return f"Rate limited by the provider. ({detail})"
    return f"Provider returned {status}: {detail}"


def _arguments(raw: str) -> dict[str, Any] | None:
    """The arguments a tool call was streamed with, or None if they were cut.

    The distinction is the whole point, and getting it wrong cost a real
    session. A model writing a 6KB file into a tool call on an 8K window ran
    out of room mid-object; the fragment would not parse, this returned an
    empty dict, and the tool layer answered "missing required arguments" by
    naming the schema. That is the correct answer to a call that sent
    nothing, and useless advice to one that was severed -- so the model sent
    the identical call six more times until the round limit stopped it.

    An empty string is a model that genuinely sent no arguments: `{}`.
    Anything that will not parse was interrupted: None, and the caller says
    so plainly.
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


def _data_url(image: dict[str, Any]) -> str:
    source = image.get("source") or {}
    return (
        f"data:{source.get('media_type', 'image/png')};base64,"
        f"{source.get('data', '')}"
    )


def _as_text(content: Any) -> str:
    """A tool result as this API wants it: a plain string.

    MCP allows a result to be a list of content blocks. This wire format has
    nowhere to put that, so the text is pulled out and joined.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    return "" if content is None else str(content)
