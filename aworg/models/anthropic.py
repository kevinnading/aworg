"""Adapter for the Anthropic Messages API."""

from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from .base import Fragment, Message, ModelAdapter, ModelError


ANTHROPIC_VERSION = "2023-06-01"

#: A thinking model can be silent for a long time before its first word, so a
#: single overall deadline is wrong: it cuts off work that is going fine. What
#: should fail fast is a connection that is not there, and what should fail
#: eventually is a stream that has genuinely stalled -- hence a short connect
#: and a generous gap between chunks.
STREAM_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)


class AnthropicAdapter(ModelAdapter):
    provider = "anthropic"

    @property
    def default_base_url(self) -> str:
        return "https://api.anthropic.com"

    async def stream(
        self, messages: list[Message], system: str
    ) -> AsyncIterator[Fragment]:
        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "stream": True,
            "messages": [
                {
                    "role": "user" if m.role == "owner" else "assistant",
                    "content": m.content,
                }
                for m in messages
            ],
        }
        if system:
            payload["system"] = system

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
                        if event.get("type") == "content_block_delta":
                            delta = event.get("delta") or {}
                            if delta.get("type") == "text_delta":
                                yield Fragment("reply", delta.get("text", ""))
                            elif delta.get("type") == "thinking_delta":
                                yield Fragment("thinking", delta.get("thinking", ""))
                        elif event.get("type") == "error":
                            detail = (event.get("error") or {}).get("message", "unknown error")
                            raise ModelError(detail)
        except httpx.RequestError as exc:
            raise ModelError(f"Could not reach {self.base_url}: {exc}") from exc


def _describe(status: int, body: str) -> str:
    """Turn a provider error into something an owner can act on."""
    try:
        detail = (json.loads(body).get("error") or {}).get("message")
    except (json.JSONDecodeError, AttributeError):
        detail = None
    detail = detail or body[:300].strip() or "no detail provided"

    if status == 401:
        return f"Authentication failed - check the credential. ({detail})"
    if status == 404:
        return f"Model not found - check the model identifier. ({detail})"
    if status == 429:
        return f"Rate limited by the provider. ({detail})"
    return f"Provider returned {status}: {detail}"
