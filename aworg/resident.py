"""The Resident.

In Milestone 1 the Resident can only converse -- it has no tools, no workspace
access, and no ability to act. What it does have is continuity: one ongoing
conversation that outlives the browser tab and the process, and an identity
that is independent of whichever model is currently behind it.

That independence is the point of this milestone. The owner can change the mind
the Resident thinks with, mid-conversation, and the Resident carries on as
itself. Everything here is arranged to make that true rather than to make it
look true.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from .models import Message, ModelError, build_adapter
from .secrets import SecretStore, credential_ref
from .storage import Store


class Resident:
    def __init__(self, store: Store, secrets: SecretStore):
        self.store = store
        self.secrets = secrets

    # -- state ----------------------------------------------------------

    def primary_connection(self) -> dict[str, Any] | None:
        connection_id = self.store.get_resident()["primary_connection_id"]
        if not connection_id:
            return None
        return self.store.get_connection(connection_id)

    def state(self) -> dict[str, Any]:
        """What the owner interface needs to describe the Resident right now."""
        connection = self.primary_connection()
        if connection is None:
            return {
                "status": "unconfigured",
                "detail": "No model is connected yet.",
                "model_label": None,
                "connection": None,
            }
        if not self.secrets.has(credential_ref(connection["id"])):
            return {
                "status": "unconfigured",
                "detail": f"{connection['name']} has no credential.",
                "model_label": _label(connection),
                "connection": connection,
            }
        return {
            "status": "present",
            "detail": "Resident is present.",
            "model_label": _label(connection),
            "connection": connection,
        }

    def conversation(self) -> dict[str, Any]:
        conversation_id = self.store.current_conversation_id()
        return {
            "id": conversation_id,
            "messages": self.store.messages(conversation_id),
        }

    # -- conversing -----------------------------------------------------

    #: Characters per token, for when the model cannot be asked. Measured
    #: against llama.cpp's own count on a real conversation: about 9% high,
    #: which errs the safe way.
    CHARS_PER_TOKEN = 3.6

    async def context_usage(self) -> dict[str, Any]:
        """How full the window is, built from exactly what the next turn sends.

        Exact when the model's server will count; estimated otherwise, and
        the answer says which. The window comes from the connection -- None
        if nobody has set it, in which case there is a count but no percent.
        """
        conversation_id = self.store.current_conversation_id()
        config = self.store.get_resident()
        history = [
            Message(role=m["role"], content=m["content"])
            for m in self.store.messages(conversation_id)
        ]
        system = config["system_prompt"]
        chars = len(system) + sum(len(m.content) for m in history)
        estimate = int(chars / self.CHARS_PER_TOKEN)

        connection = self.primary_connection()
        tokens, exact, window = estimate, False, None
        if connection is not None:
            window = connection.get("context")
            api_key = self.secrets.get(credential_ref(connection["id"]))
            if api_key:
                try:
                    counted = await build_adapter(connection, api_key).count_tokens(
                        history, system
                    )
                except ModelError:
                    counted = None
                if counted is not None:
                    tokens, exact = counted, True

        return {
            "tokens": tokens,
            "exact": exact,
            "window": window,
            "percent": round(100 * tokens / window, 1) if window else None,
            "messages": len(history),
            "chars_per_token": self.CHARS_PER_TOKEN,
        }

    async def respond_to(self, text: str) -> AsyncIterator[dict[str, Any]]:
        """Take the owner's message and stream back the Resident's reply.

        Yields events rather than raw text so the owner interface can
        distinguish a reply arriving from a failure to reply.
        """
        conversation_id = self.store.current_conversation_id()

        # The owner said it, so it happened. Record it before attempting a
        # reply -- if the model is unreachable, the message should not vanish.
        self.store.add_message(conversation_id, "owner", text)

        connection = self.primary_connection()
        if connection is None:
            yield {
                "type": "error",
                "message": "No model is connected. Open Settings to connect one.",
            }
            return

        api_key = self.secrets.get(credential_ref(connection["id"]))
        if not api_key:
            yield {
                "type": "error",
                "message": f"{connection['name']} has no credential. Add one in Settings.",
            }
            return

        resident_config = self.store.get_resident()
        history = [
            Message(role=m["role"], content=m["content"])
            for m in self.store.messages(conversation_id)
        ]

        label = _label(connection)
        collected: list[str] = []
        thought = False

        try:
            adapter = build_adapter(connection, api_key)
            async for fragment in adapter.stream(
                history, system=resident_config["system_prompt"]
            ):
                if fragment.kind == "thinking":
                    # Thinking is not what the Resident said, so it is never
                    # kept. It is still reported, because a model that thinks
                    # for thirty seconds before its first word is
                    # indistinguishable from one that has hung.
                    thought = True
                    yield {"type": "thinking", "text": fragment.text}
                    continue
                collected.append(fragment.text)
                yield {"type": "delta", "text": fragment.text}
        except ModelError as exc:
            # A partial reply is still something the Resident said. Keep it,
            # so the conversation reflects what actually happened.
            if collected:
                self.store.add_message(
                    conversation_id, "resident", "".join(collected), label
                )
            yield {"type": "error", "message": str(exc)}
            return

        reply = "".join(collected)
        if reply.strip():
            self.store.add_message(conversation_id, "resident", reply, label)
        elif thought:
            # It reasoned its whole budget away and never answered. Silence
            # here would look identical to a crash, and the owner would have
            # no idea the model was the thing that needed changing.
            yield {
                "type": "error",
                "message": (
                    f"{label} spent its whole reply thinking and never answered. "
                    "Its reasoning budget is likely too small for this request."
                ),
            }
            return
        yield {"type": "done", "model_label": label}


def _label(connection: dict[str, Any]) -> str:
    """How a reply is attributed in the conversation.

    Showing which mind produced which reply is what makes switching models
    mid-conversation legible instead of mysterious.
    """
    return f"{connection['name']} ({connection['model']})"
