"""The Model Pool's adapter registry."""

from __future__ import annotations

from .. import providers
from .anthropic import AnthropicAdapter
from .base import Fragment, Message, ModelAdapter, ModelError, ToolCall
from .openai_compatible import OpenAICompatibleAdapter
from .openai_responses import OpenAIResponsesAdapter


#: The wire formats. Providers are chosen by name and resolved to one of
#: these; see aworg/providers.py for why that is the right way round.
#:
#: Three now rather than two, and the third is not a third *vendor*. OpenAI
#: speaks two different APIs and the newer models are built around the
#: second, so "openai-compatible" keeps its meaning -- the de facto standard
#: that most of the world implements -- and OpenAI proper gets its own.
ADAPTERS: dict[str, type[ModelAdapter]] = {
    "anthropic": AnthropicAdapter,
    "openai-compatible": OpenAICompatibleAdapter,
    "openai-responses": OpenAIResponsesAdapter,
}

#: Shown in the owner interface when defining a connection.
PROVIDER_LABELS = {key: p["label"] for key, p in providers.PROVIDERS.items()}

#: What a model is good for. Nothing routes on these yet -- see the
#: Milestone 1 notes on why they exist now anyway.
CAPABILITY_TAGS = ["reasoning", "coding", "fast", "cheap", "vision", "local"]


def build_adapter(connection: dict, api_key: str) -> ModelAdapter:
    """The adapter for a connection, configured from its provider's profile.

    The profile decides the wire format, so a connection saved as Anthropic
    is spoken to as Anthropic whatever URL it points at. That is what makes
    the base URL safe to leave editable: a mistake fails at the first
    request and says what it was, instead of half-working.
    """
    profile = providers.profile(connection["provider"])
    adapter_class = ADAPTERS.get(profile["adapter"])
    if adapter_class is None:                      # pragma: no cover - guarded above
        raise ModelError(f"Unknown wire format: {profile['adapter']}")
    return adapter_class(
        model=connection["model"],
        api_key=api_key,
        base_url=connection.get("base_url") or profile["base_url"] or None,
        reasoning=connection.get("reasoning") or "auto",
        context=connection.get("context"),
        auth=profile["auth"],
        headers=profile["headers"],
        # The budget is per connection and shared by everything using it, so
        # it is keyed by the connection's own id rather than by model name.
        connection_id=connection.get("id") or "",
        # The owner's figure if they have set one, otherwise the provider's
        # entry tier. A new key is a tier-1 key, and finding that out by
        # being cut off halfway through a job is a poor introduction.
        tokens_per_minute=(
            connection.get("tokens_per_minute")
            if connection.get("tokens_per_minute")
            else profile.get("tpm") or None
        ),
    )


__all__ = [
    "Fragment",
    "Message",
    "ModelAdapter",
    "ModelError",
    "ToolCall",
    "ADAPTERS",
    "PROVIDER_LABELS",
    "CAPABILITY_TAGS",
    "build_adapter",
]
