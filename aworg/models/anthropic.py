"""Adapter for the Anthropic Messages API."""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

from .base import Fragment, Message, ModelAdapter, ModelError


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
        self, messages: list[Message], system: str
    ) -> AsyncIterator[Fragment]:
        payload: dict[str, Any] = {
            "model": self.model,
            # The API requires a ceiling, so this is set past what any current
            # model will produce rather than to a number that would cut a
            # reply short. A provider that rejects it says so plainly, which
            # is a better failure than a reply that stops mid-sentence.
            "max_tokens": MAX_TOKENS,
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

        headers = self._headers()

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
