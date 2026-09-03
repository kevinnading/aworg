"""The Model Pool's adapter registry."""

from __future__ import annotations

from .anthropic import AnthropicAdapter
from .base import Fragment, Message, ModelAdapter, ModelError
from .openai_compatible import OpenAICompatibleAdapter


PROVIDERS: dict[str, type[ModelAdapter]] = {
    "anthropic": AnthropicAdapter,
    "openai-compatible": OpenAICompatibleAdapter,
}

#: Shown in the owner interface when defining a connection.
PROVIDER_LABELS = {
    "anthropic": "Anthropic",
    "openai-compatible": "OpenAI-compatible",
}

#: What a model is good for. Nothing routes on these yet -- see the
#: Milestone 1 notes on why they exist now anyway.
CAPABILITY_TAGS = ["reasoning", "coding", "fast", "cheap", "vision", "local"]


def build_adapter(connection: dict, api_key: str) -> ModelAdapter:
    provider = connection["provider"]
    adapter_class = PROVIDERS.get(provider)
    if adapter_class is None:
        raise ModelError(f"Unknown provider: {provider}")
    return adapter_class(
        model=connection["model"],
        api_key=api_key,
        base_url=connection.get("base_url"),
        reasoning=connection.get("reasoning") or "auto",
        context=connection.get("context"),
    )


__all__ = [
    "Fragment",
    "Message",
    "ModelAdapter",
    "ModelError",
    "PROVIDERS",
    "PROVIDER_LABELS",
    "CAPABILITY_TAGS",
    "build_adapter",
]
