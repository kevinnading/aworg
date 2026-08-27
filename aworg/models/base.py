"""The provider-neutral model interface.

AWORG must never become the interface to one company's model. Everything above
this layer -- the Resident, the server, the owner interface -- speaks only in
the vocabulary defined here. Provider-specific details are confined to the
adapters, so adding a provider never means touching the Resident.

The interface is deliberately narrow. It grows when a milestone needs it to,
not in anticipation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator


@dataclass
class Message:
    """One turn in a conversation, in AWORG's own vocabulary.

    Internally the two roles are "owner" and "resident". Adapters translate
    those into whatever a given provider calls them. The vocabulary of the
    product does not bend to the vocabulary of an API.
    """

    role: str
    content: str


class ModelError(Exception):
    """A model could not be reached, or refused the request.

    Carries a message fit to show the owner directly. The owner should learn
    that a credential is invalid or an endpoint is unreachable without having
    to read a stack trace.
    """


class ModelAdapter:
    """Translates between AWORG and one external provider."""

    #: Short provider identifier, e.g. "anthropic".
    provider: str = "unknown"

    def __init__(self, model: str, api_key: str, base_url: str | None = None):
        self.model = model
        self.api_key = api_key
        self.base_url = (base_url or self.default_base_url).rstrip("/")

    @property
    def default_base_url(self) -> str:
        raise NotImplementedError

    async def stream(self, messages: list[Message], system: str) -> AsyncIterator[str]:
        """Yield the reply as it arrives, one fragment at a time."""
        raise NotImplementedError
        yield ""  # pragma: no cover - signals an async generator to type checkers

    async def probe(self) -> None:
        """Verify the connection works. Raises ModelError if it does not."""
        async for _ in self.stream([Message("owner", "Hello")], system=""):
            return
