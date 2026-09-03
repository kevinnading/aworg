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


@dataclass
class Fragment:
    """One piece of a reply, as it arrives.

    Some models think out loud before answering, and they send that thinking
    down the same stream as the answer. It is not the answer: it must not be
    saved as what the Resident said, and it must not be silently dropped
    either -- a Resident that shows nothing for thirty seconds looks broken,
    and an owner cannot tell a model that is working from one that has hung.

    So a fragment says which it is, and everything above this layer decides
    what to do about it.
    """

    #: "reply" -- part of the answer. "thinking" -- reasoning on the way to it.
    kind: str
    text: str


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

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str | None = None,
        reasoning: str = "auto",
        context: int | None = None,
    ):
        self.model = model
        self.api_key = api_key
        self.base_url = (base_url or self.default_base_url).rstrip("/")
        #: "auto" leaves the model as configured; "off" asks it not to think
        #: before answering. Thinking costs real time -- a 9B spent 99 seconds
        #: on an eighty-word paragraph -- and whether that is worth paying
        #: depends on the model and the job, so it is the owner's choice and
        #: belongs to the connection rather than being decided here.
        self.reasoning = reasoning
        #: How many tokens a single request may carry, or None if nobody has
        #: said. Local servers announce it; hosted ones mostly do not, and a
        #: request past it is refused outright rather than trimmed -- so this
        #: is the number everything above here has to fit inside.
        self.context = context

    async def count_tokens(self, messages: list[Message], system: str) -> int | None:
        """How many tokens this conversation costs, by the model's own count.

        Only the model's tokenizer knows. A server that exposes it answers
        exactly; everything else returns None and the caller estimates,
        which is roughly a tenth out -- close enough to be useful, far enough
        that the interface says which it is showing.
        """
        return None

    async def detect_context(self) -> int | None:
        """Ask the server how big its window is, if it will say.

        Most will not. Returning None is the ordinary case, not a failure.
        """
        return None

    @property
    def default_base_url(self) -> str:
        raise NotImplementedError

    async def stream(
        self, messages: list[Message], system: str
    ) -> AsyncIterator[Fragment]:
        """Yield the reply as it arrives, one fragment at a time."""
        raise NotImplementedError
        yield Fragment("reply", "")  # pragma: no cover - marks this a generator

    async def probe(self) -> None:
        """Verify the connection works. Raises ModelError if it does not."""
        async for _ in self.stream([Message("owner", "Hello")], system=""):
            return
