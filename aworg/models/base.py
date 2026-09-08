"""The provider-neutral model interface.

AWORG must never become the interface to one company's model. Everything above
this layer -- the Resident, the server, the owner interface -- speaks only in
the vocabulary defined here. Provider-specific details are confined to the
adapters, so adding a provider never means touching the Resident.

The interface is deliberately narrow. It grows when a milestone needs it to,
not in anticipation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator


@dataclass
class Message:
    """One turn in a conversation, in AWORG's own vocabulary.

    Internally the roles are "owner", "resident" and "tool". Adapters
    translate those into whatever a given provider calls them. The
    vocabulary of the product does not bend to the vocabulary of an API.

    `blocks` carries MCP content blocks for the messages that are more than
    prose -- a reply that asked for tools, and the results that answered it.
    It is None for ordinary text, which is most messages. When it is set it
    is the truth and `content` is a rendering of it for display.
    """

    role: str
    content: str
    blocks: list[dict[str, Any]] | None = None


@dataclass
class ToolCall:
    """A model asking for a tool, in MCP's terms.

    `id` is the provider's own correlation id and must come back attached to
    the result. Both wire formats reject a result whose id matches no call,
    which is what forces a tool exchange to be kept together when history is
    trimmed to fit a window.
    """

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


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

    #: "reply" -- part of the answer. "thinking" -- reasoning on the way to
    #: it. "tool_use" -- the model asking to run something, which is not
    #: text at all and carries a ToolCall instead.
    kind: str
    text: str = ""
    tool_call: "ToolCall | None" = None


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
        auth: str = "bearer",
        headers: dict[str, str] | None = None,
    ):
        self.model = model
        self.api_key = api_key
        self.base_url = (base_url or self.default_base_url).rstrip("/")
        #: How this provider wants the credential presented, and anything
        #: else it insists on. Both come from the provider profile rather
        #: than being decided here, so that adding a provider stays a data
        #: entry: see aworg/providers.py.
        self.auth = auth
        self.extra_headers = dict(headers or {})
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

    def _auth_headers(self) -> dict[str, str]:
        """The credential, presented the way this provider asks for it.

        A local server that checks nothing still gets whatever the owner
        stored, because a connection with no credential at all is a
        different state -- one the interface reports -- and quietly
        inventing one here would hide it.
        """
        if self.auth == "x-api-key":
            return {"x-api-key": self.api_key}
        if self.auth == "none":
            return {}
        return {"Authorization": f"Bearer {self.api_key}"}

    async def list_models(self) -> list[str]:
        """What this provider will serve, if it will say.

        An empty list means it would not say, which is not the same as
        having no models -- the interface distinguishes them, because one is
        a provider that does not publish a list and the other is a
        misconfigured connection.
        """
        return []

    #: Whether this adapter can carry tool calls at all. An owner pointed at
    #: a provider that cannot is told so, rather than watching a Resident
    #: that never reaches for anything and looks merely unhelpful.
    supports_tools: bool = False

    async def stream(
        self,
        messages: list[Message],
        system: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[Fragment]:
        """Yield the reply as it arrives, one fragment at a time.

        `tools` is a list of MCP tool descriptors, or None for a plain
        conversation. An adapter translates them into its provider's shape;
        nothing above this layer knows what that shape is.
        """
        raise NotImplementedError
        yield Fragment("reply", "")  # pragma: no cover - marks this a generator

    async def probe(self) -> None:
        """Verify the connection works. Raises ModelError if it does not."""
        async for _ in self.stream([Message("owner", "Hello")], system=""):
            return
