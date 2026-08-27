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

from .base import Message, ModelAdapter, ModelError


class OpenAICompatibleAdapter(ModelAdapter):
    provider = "openai-compatible"

    @property
    def default_base_url(self) -> str:
        return "https://api.openai.com/v1"

    async def stream(self, messages: list[Message], system: str) -> AsyncIterator[str]:
        wire: list[dict[str, str]] = []
        if system:
            wire.append({"role": "system", "content": system})
        wire.extend(
            {
                "role": "user" if m.role == "owner" else "assistant",
                "content": m.content,
            }
            for m in messages
        )

        payload = {"model": self.model, "messages": wire, "stream": True}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
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
                        text = (choices[0].get("delta") or {}).get("content")
                        if text:
                            yield text
        except httpx.RequestError as exc:
            raise ModelError(f"Could not reach {self.base_url}: {exc}") from exc


def _describe(status: int, body: str) -> str:
    try:
        detail = (json.loads(body).get("error") or {}).get("message")
    except (json.JSONDecodeError, AttributeError):
        detail = None
    detail = detail or body[:300].strip() or "no detail provided"

    if status == 401:
        return f"Authentication failed - check the credential. ({detail})"
    if status == 404:
        return f"Not found - check the model identifier and endpoint. ({detail})"
    if status == 429:
        return f"Rate limited by the provider. ({detail})"
    return f"Provider returned {status}: {detail}"
