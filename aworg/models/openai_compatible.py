"""Adapter for OpenAI-style chat completion endpoints.

Deliberately not called "the OpenAI adapter". This shape has become a de facto
interface, and one adapter covers OpenAI itself, most third-party gateways, and
local model servers running on the owner's own hardware. Supporting it from the
first milestone is what makes model agnosticism a fact rather than a claim: an
owner can point their Resident at a model running on their own machine without
AWORG needing to know anything about it.
"""

from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from .base import Fragment, Message, ModelAdapter, ModelError


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

    @property
    def default_base_url(self) -> str:
        return "https://api.openai.com/v1"

    def _wire(self, messages: list[Message], system: str) -> list[dict[str, str]]:
        wire: list[dict[str, str]] = []
        if system:
            wire.append({"role": "system", "content": system})
        wire.extend(
            {"role": "user" if m.role == "owner" else "assistant", "content": m.content}
            for m in messages
        )
        return wire

    async def stream(
        self, messages: list[Message], system: str
    ) -> AsyncIterator[Fragment]:
        wire = self._wire(messages, system)

        payload: dict[str, Any] = {"model": self.model, "messages": wire, "stream": True}
        if self.reasoning == "off":
            # The convention llama.cpp and most gateways accept. A server that
            # does not understand it ignores it, which is the right failure:
            # the reply is slower than asked for, not absent.
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        splitter = _ThinkSplitter()

        try:
            async with httpx.AsyncClient(timeout=STREAM_TIMEOUT) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
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
                        if not chunk or chunk == "[DONE]":
                            continue
                        try:
                            event = json.loads(chunk)
                        except json.JSONDecodeError:
                            continue
                        choices = event.get("choices") or []
                        if not choices:
                            continue
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

                    for kind, part in splitter.drain():
                        yield Fragment(kind, part)
        except httpx.RequestError as exc:
            raise ModelError(f"Could not reach {self.base_url}: {exc}") from exc


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
