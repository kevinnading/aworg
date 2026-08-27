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

    def new_conversation(self) -> dict[str, Any]:
        self.store.new_conversation()
        return self.conversation()

    # -- conversing -----------------------------------------------------

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

        try:
            adapter = build_adapter(connection, api_key)
            async for fragment in adapter.stream(
                history, system=resident_config["system_prompt"]
            ):
                collected.append(fragment)
                yield {"type": "delta", "text": fragment}
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
        yield {"type": "done", "model_label": label}


def _label(connection: dict[str, Any]) -> str:
    """How a reply is attributed in the conversation.

    Showing which mind produced which reply is what makes switching models
    mid-conversation legible instead of mysterious.
    """
    return f"{connection['name']} ({connection['model']})"
