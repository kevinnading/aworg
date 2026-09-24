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

from .. import ratelimit


#: Connections whose server has refused a picture.
#:
#: Shared by the adapters and keyed by connection id, because an adapter is
#: built fresh for every request so anything learned on an instance is
#: forgotten at once. Runtime only: a server that gains sight between
#: restarts -- llama.cpp handed an mmproj, say -- deserves to be believed
#: again rather than written off for good.
#:
#: What it is for: a text-only model sent a picture answers with an error,
#: and the picture stays in the conversation, so every following turn sends
#: it again and dies the same way. One `read_image` call bricked a
#: conversation permanently. The tool still runs and its text still arrives;
#: only the pixels are dropped, and the model is told they were.
BLIND: set[str] = set()


def refused_a_picture(status: int, body: str) -> bool:
    """Whether this failure is the server saying it cannot see.

    Matched on wording rather than status, because the status is not agreed
    on: llama.cpp answers 500, others 400 or 415. Deliberately narrow -- it
    wants two independent signals, a mention of images and a refusal -- so
    that an unrelated failure is never mistaken for this and quietly retried
    with the owner's evidence stripped out of it.
    """
    if status < 400:
        return False
    lowered = body.lower()
    if "image" not in lowered and "vision" not in lowered:
        return False
    return any(
        phrase in lowered
        for phrase in (
            "not supported", "unsupported", "does not support",
            "mmproj", "cannot process", "no vision",
        )
    )


def picture_omitted(count: int) -> str:
    """What replaces a picture that could not be sent.

    Said rather than silently removed. A Resident that asked to look at a
    file and was handed nothing would conclude the file was empty; one told
    the picture could not be shown knows the difference between "there is
    nothing there" and "I cannot see it", and can say so to its owner.
    """
    return (
        f"({count} picture{'s' if count != 1 else ''} not shown: the model "
        "behind this connection cannot see images.)"
    )


@dataclass
class Message:
    """One turn in a conversation, in AWORG's own vocabulary.

    Internally the roles are "owner", "resident", "tool" and "watch".
    Adapters translate those into whatever a given provider calls them. The
    vocabulary of the product does not bend to the vocabulary of an API.

    Every adapter's rule is the same and stated the same way: "resident" is
    the assistant, and **everything else is the Resident being told
    something**, so it travels as user. A new role therefore needs no
    adapter change, which is the point -- two adapters once tested for
    "owner" instead, and under that rule "watch" would have reached the
    model as words the Resident itself had said.

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
    #: The model ran out of room mid-call and its arguments arrived as a
    #: fragment that will not parse. Emphatically not the same as a call with
    #: no arguments, and telling the two apart is the difference between a
    #: model that shortens its next attempt and one that repeats the same
    #: impossible call until the round limit stops it.
    truncated: bool = False


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
    #: text at all and carries a ToolCall instead. "waiting" -- nothing is
    #: happening and here is why, which exists because a Resident silent for
    #: forty seconds and a Resident that has hung look identical from
    #: outside.
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
        connection_id: str = "",
        tokens_per_minute: int | None = None,
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
        #: Which stored connection this adapter is speaking for. Kept as
        #: well as folded into the budget key below, because anything an
        #: adapter learns about a provider has to outlive the adapter --
        #: one is built per request -- and the connection is the thing it
        #: was actually learned about. See BLIND.
        self.connection_id = connection_id or f"{self.provider}:{model}"
        #: This connection's tokens-per-minute allowance, as a budget shared
        #: with everything else using the same connection -- the Resident and
        #: its workers spend from one pot, because the provider counts them
        #: together. None where nothing is stated, which is a local model.
        self.budget = ratelimit.budget_for(self.connection_id, tokens_per_minute)
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

    #: Characters per token, for estimating what a request will cost before
    #: sending it. Deliberately pessimistic -- undercounting spends more of
    #: the allowance than was reserved, which is the failure this avoids.
    CHARS_PER_TOKEN = 3.4

    def estimate_cost(self, payload: Any) -> int:
        """Roughly what this request will be charged, in tokens.

        From the serialised payload, because that is what actually goes on
        the wire and it is the one thing every adapter has in the same shape.
        A real tokenizer would be better and is not available here; the
        allowance carries headroom precisely because this is an estimate.

        The reply is charged too and cannot be known in advance, so a flat
        allowance for it is added. A turn that reserves only its input and
        then receives four thousand tokens of answer has spent more than it
        booked.
        """
        import json as _json

        try:
            size = len(_json.dumps(payload))
        except (TypeError, ValueError):
            size = 0
        return int(size / self.CHARS_PER_TOKEN) + self.REPLY_ALLOWANCE

    #: Assumed cost of a reply, in tokens. Not a cap on anything -- just the
    #: part of the bill that cannot be counted before it arrives.
    REPLY_ALLOWANCE = 1200

    async def wait_for_budget(self, payload: Any) -> float:
        """Hold until this request fits the allowance. Returns seconds waited.

        Zero is the ordinary answer. Anything else is reported upward as a
        `waiting` fragment by the caller, because the alternative is a
        Resident that goes quiet and an owner who cannot tell that from a
        crash.
        """
        waited = 0.0

        def note(seconds: float) -> None:
            nonlocal waited
            waited = seconds

        await self.budget.reserve(self.estimate_cost(payload), on_wait=note)
        return waited

    async def probe(self) -> None:
        """Verify the connection works. Raises ModelError if it does not."""
        async for _ in self.stream([Message("owner", "Hello")], system=""):
            return
