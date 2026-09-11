"""The providers an owner can connect to, and what each one needs.

A provider is not a wire format. Almost everything below speaks OpenAI's
shape, and picking "OpenAI-compatible" from a list is not a choice an owner
should have to make -- they know they are connecting to Groq, not that Groq
happens to implement someone else's API. So the list is of providers by
name, and which format each speaks is a field inside the profile rather than
the thing being chosen.

That leaves exactly two adapters underneath, which is the point. Adding a
provider here is a data entry: a base URL, how it wants the key presented,
and how to ask it what models it has. It is not a code change, and it must
stay that way -- the moment a provider needs its own branch in the adapter,
that branch belongs behind a flag in this file rather than in a growing
`if provider ==` somewhere below.

`base_url` is a starting point, never a lock. An owner behind a proxy, a
gateway or a company mirror has a legitimate reason to point Anthropic
somewhere that is not api.anthropic.com, and a form that will not let them
is a form they cannot use. What protects against pasting an OpenAI URL under
an Anthropic profile is not the field being read-only -- it is that the
adapter comes from the profile, so the mistake fails immediately and says
what it was, rather than half-working.
"""

from __future__ import annotations

from typing import Any


#: How a provider wants the credential presented.
#:
#: "bearer"   -- Authorization: Bearer <key>, which is most of them.
#: "x-api-key" -- Anthropic's header.
#: "none"      -- local servers that do not check, though AWORG still stores
#:                something so the connection has a credential to be missing.
AUTH_STYLES = ("bearer", "x-api-key", "none")

#: What is known about whether a provider's models can use tools.
#:
#: "yes"      -- every model it serves can.
#: "no"       -- none can.
#: "per-model" -- it varies, and the provider will say which.
#: "unknown"  -- it varies and nobody will say; it has to be tried.
#:
#: The fourth is not a gap in this table. A connection that says "tool
#: support unknown" is telling the owner something true; one that guesses
#: "yes" and is wrong sends a Resident to reach for hands it does not have.
TOOL_SUPPORT = ("yes", "no", "per-model", "unknown")


def _profile(
    label: str,
    adapter: str,
    base_url: str = "",
    *,
    auth: str = "bearer",
    headers: dict[str, str] | None = None,
    models: str = "list",
    tools: str = "unknown",
    note: str = "",
    generic: bool = False,
) -> dict[str, Any]:
    return {
        "label": label,
        #: Which of the two wire formats this speaks.
        "adapter": adapter,
        #: Pre-filled, and editable. See the module docstring.
        "base_url": base_url,
        "auth": auth,
        #: Anything the provider requires beyond the credential.
        "headers": headers or {},
        #: "list" -- ask the provider. "manual" -- the owner types it.
        "models": models,
        "tools": tools,
        #: Shown under the field in the form, when there is something the
        #: owner would otherwise have to go and find out.
        "note": note,
        #: The two fall-throughs, for anything not named here.
        "generic": generic,
    }


PROVIDERS: dict[str, dict[str, Any]] = {
    # -- hosted ------------------------------------------------------------
    "openai": _profile(
        "OpenAI", "openai-responses", "https://api.openai.com/v1",
        tools="yes",
        note="Speaks OpenAI's Responses API, which is what the newer models "
             "are built around. For a gateway or proxy that only offers "
             "/chat/completions, use Custom (OpenAI-compatible) instead.",
    ),
    "anthropic": _profile(
        "Anthropic", "anthropic", "https://api.anthropic.com",
        auth="x-api-key", tools="yes",
    ),
    "gemini": _profile(
        "Google Gemini", "openai-compatible",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        tools="yes",
        note="Google's OpenAI-compatible endpoint, rather than the Gemini API.",
    ),
    "groq": _profile(
        "Groq", "openai-compatible", "https://api.groq.com/openai/v1",
        tools="per-model",
    ),
    "openrouter": _profile(
        "OpenRouter", "openai-compatible", "https://openrouter.ai/api/v1",
        headers={"HTTP-Referer": "https://github.com/aworg", "X-Title": "AWORG"},
        tools="per-model",
        note="One connection, many models. Attribution headers are sent for you.",
    ),
    "deepseek": _profile(
        "DeepSeek", "openai-compatible", "https://api.deepseek.com/v1",
        tools="yes",
    ),
    "mistral": _profile(
        "Mistral", "openai-compatible", "https://api.mistral.ai/v1",
        tools="yes",
    ),
    "xai": _profile(
        "xAI", "openai-compatible", "https://api.x.ai/v1",
        tools="yes",
    ),
    "together": _profile(
        "Together", "openai-compatible", "https://api.together.xyz/v1",
        tools="per-model",
    ),
    "fireworks": _profile(
        "Fireworks", "openai-compatible", "https://api.fireworks.ai/inference/v1",
        tools="per-model",
    ),

    # -- local -------------------------------------------------------------
    #
    # These need no credential, which is exactly why they are worth naming
    # separately: an owner running llama.cpp should not have to invent a key
    # to satisfy a form.
    "llamacpp": _profile(
        "llama.cpp", "openai-compatible", "http://127.0.0.1:8080/v1",
        auth="none", tools="per-model",
        note="Tool support is read from the server's own chat template, so it is known per model.",
    ),
    "ollama": _profile(
        "Ollama", "openai-compatible", "http://127.0.0.1:11434/v1",
        auth="none", tools="per-model",
    ),
    "lmstudio": _profile(
        "LM Studio", "openai-compatible", "http://127.0.0.1:1234/v1",
        auth="none", tools="per-model",
    ),
    "vllm": _profile(
        "vLLM", "openai-compatible", "http://127.0.0.1:8000/v1",
        auth="none", tools="per-model",
    ),

    # -- the fall-throughs -------------------------------------------------
    #
    # Kept last, and kept: a list of named providers is out of date the week
    # it ships, and an owner with something not on it should not be stuck.
    # These are also the two values connections were stored with before this
    # file existed, so nothing needs migrating.
    "openai-compatible": _profile(
        "Custom (OpenAI-compatible)", "openai-compatible",
        tools="unknown", generic=True,
        note="Anything speaking OpenAI's API. Give it the base URL ending in /v1.",
    ),
    "anthropic-compatible": _profile(
        "Custom (Anthropic-compatible)", "anthropic",
        auth="x-api-key", tools="unknown", generic=True,
        note="Anything speaking Anthropic's Messages API.",
    ),
}


#: The order they are offered in. Hosted first because that is what most
#: owners are reaching for, local next, and the two escape hatches last.
ORDER = list(PROVIDERS)


def profile(provider: str) -> dict[str, Any]:
    """The profile for a stored connection's provider.

    Falls back to the generic OpenAI-compatible profile rather than raising.
    A connection saved against a provider this build no longer knows about
    is still a connection the owner can reach; refusing to load it would
    lose them the credential too.
    """
    return PROVIDERS.get(provider) or PROVIDERS["openai-compatible"]


def for_interface() -> list[dict[str, Any]]:
    """The list as the owner interface offers it."""
    return [
        {
            "id": key,
            "label": PROVIDERS[key]["label"],
            "base_url": PROVIDERS[key]["base_url"],
            "auth": PROVIDERS[key]["auth"],
            "models": PROVIDERS[key]["models"],
            "tools": PROVIDERS[key]["tools"],
            "note": PROVIDERS[key]["note"],
            "generic": PROVIDERS[key]["generic"],
        }
        for key in ORDER
    ]

