"""The Living Log: what happened, and mattered.

Three panes answer three different questions, and the whole value is in not
merging them:

    Tasks         what should be accomplished
    Activities    what is happening at this moment
    Living Log    what happened, and mattered

Activities is a window. It shows work while it runs, it is runtime state, and
it is gone on restart -- which is correct, because "what is happening right
now" has no meaning for a moment that has passed. The Living Log is the
opposite of that in every respect. It is durable, it is short, and nothing
reaches it because it occurred; it reaches it because someone judged that it
mattered.

**This file is where the judging happens.** The Activity Manager deliberately
has no opinions -- it tracks and it emits, and it will not decide that
something belongs here. So the Living Log subscribes like anything else and
makes that call itself. Adding a new thing worth remembering is a rule in
`matters`, not a change to the thing being remembered.

The bar is high on purpose. A log that records every successful tool call is
a second Activities pane with worse latency, and an owner learns within a day
to stop reading it. What earns an entry is a change of state the owner would
want to find later, or something going wrong. Ordinary success is not news.

Eventually this is what the autonomous repair loop reads. That is the reason
for `ALARM` being a separate level rather than a hotter shade of `CONCERN`:
one means something failed and was dealt with, the other means something is
wrong *now* and nobody asked for it. A loop that cannot tell those apart
either wakes for everything or sleeps through the outage.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any


#: Worth remembering. A state change an owner would want to find later.
NOTE = "note"

#: Something went wrong, and was handled or is over. A tool that failed, a
#: worker whose calls did not all land, a task that got stuck. The Resident
#: usually already knows; this is so the owner can find it without reading
#: the conversation back.
CONCERN = "concern"

#: Something is wrong now, and nobody asked for it. Reserved for exactly
#: that -- an alarm that fires for ordinary failure is an alarm nobody
#: answers. Today the only thing that raises one is a program dying on its
#: own; when the repair loop arrives this is what it will wake for.
ALARM = "alarm"

LEVELS = (NOTE, CONCERN, ALARM)


def _what_happened(activity: dict[str, Any]) -> str:
    """What was asked for, and what came back.

    Both halves, because either alone is close to useless. "execute_command
    failed -- exit 1" names neither the command nor the complaint, and an
    owner reading it in the morning has to go and find the conversation to
    learn anything at all. The Activity already carries what it was called
    with; this is only a matter of not throwing it away.

    The Activity itself keeps the whole output, and the entry links to it --
    but Activities are runtime state and are forgotten in time, so the line
    has to stand up on its own once that link goes dead.
    """
    asked = (activity.get("detail") or "").strip()
    came_back = (activity.get("error") or "").strip()
    summary = (activity.get("summary") or "").strip()
    # `error` is usually the message; `summary` is the short form the caller
    # was shown. Prefer the message, fall back to the short form, and if
    # neither says anything, say that rather than showing an empty box.
    outcome = came_back or summary or "It gave no reason."
    if asked and outcome:
        return f"{asked}\n\n{outcome}"
    return asked or outcome


class Journal:
    """The Living Log, and the opinions about what belongs in it.

    Backed by the store rather than by memory, because the point of this pane
    is that it survives the restart that clears Activities. An owner coming
    back in the morning to find out what happened overnight is the case this
    is for, and a log that empties when the Aworg restarts answers that
    question with silence.
    """

    #: How many entries to keep. Small deliberately. This is a log meant to be
    #: read by a person and by a model with a finite window, and one that has
    #: grown to ten thousand rows is one that gets summarised instead of read,
    #: which puts a model's testimony between the owner and the evidence.
    KEEP = 500

    def __init__(self, store: Any):
        self.store = store

    # -- writing --------------------------------------------------------

    def record(
        self,
        summary: str,
        *,
        level: str = NOTE,
        kind: str = "aworg",
        source: str = "aworg",
        detail: str = "",
        activity_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Write one entry down.

        Called directly for the things that are not Activities at all -- the
        owner switching a Capability off, a reset, an Aworg starting up. Those
        have no lifecycle to subscribe to and they are exactly the kind of
        state change this pane exists to hold.
        """
        if not summary.strip():
            return None
        if level not in LEVELS:
            level = NOTE
        return self.store.add_journal_entry(
            level=level,
            kind=kind,
            source=source,
            summary=summary.strip(),
            detail=detail.strip(),
            activity_id=activity_id,
            keep=self.KEEP,
        )

    # -- reading --------------------------------------------------------

    def entries(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.store.list_journal(limit=limit)

    def clear(self) -> int:
        return self.store.clear_journal()

    # -- subscribing ----------------------------------------------------

    async def follow(self, activities: Any) -> None:
        """Watch the Activity stream and keep what matters.

        A subscriber like any other. The Activity Manager does not know this
        exists, which is the arrangement that lets a fifth thing start caring
        about Activities without either of them being touched.

        Runs until cancelled, and unsubscribes on the way out so a cancelled
        follower does not leave a queue behind that nothing ever drains.
        """
        queue = activities.subscribe()
        try:
            while True:
                message = await queue.get()
                try:
                    entry = self.matters(message)
                except Exception:                          # noqa: BLE001
                    # A rule that throws should cost that one entry. The
                    # alternative is a broken judgement silently ending the
                    # subscription, after which the Living Log stays empty
                    # and looks merely quiet.
                    continue
                if entry:
                    self._with_evidence(entry, activities)
                    self.record(**entry)
        except asyncio.CancelledError:
            raise
        finally:
            with contextlib.suppress(Exception):
                activities.unsubscribe(queue)

    #: How much of what a failing tool actually printed to keep in the entry
    #: itself. Bounded, because a build log is megabytes and this table is
    #: meant to be readable; the tail rather than the head, because the
    #: reason something failed is almost always the last thing it said.
    EVIDENCE_CHARS = 600

    def _with_evidence(self, entry: dict[str, Any], activities: Any) -> None:
        """Copy a little of the actual output into the entry, before it is lost.

        The entry links to its Activity, and for as long as the Aworg is up
        that link opens the whole of what came back. But Activities are
        runtime state -- capped at a couple of hundred and gone on restart --
        and this pane's whole purpose is to still mean something in the
        morning. An entry saying "execute_command failed, exit 1" with a dead
        link attached is a record of nothing.

        So a bounded tail comes across at the moment it is written. Not all
        of it: the Activity stays the place to go for the whole thing while
        it exists, and duplicating megabytes into a table meant to be read
        would defeat both.
        """
        activity_id = entry.get("activity_id")
        if not activity_id:
            return
        activity = activities.get(activity_id)
        payload = getattr(activity, "payload", None) if activity else None
        if not payload:
            return
        text = payload if isinstance(payload, str) else str(payload)
        text = text.strip()
        if not text:
            return
        if len(text) > self.EVIDENCE_CHARS:
            text = "…" + text[-self.EVIDENCE_CHARS:]
        # Only if it says something the entry does not already say. A tool
        # whose output is exactly its error message should not print it
        # twice.
        if text in (entry.get("detail") or ""):
            return
        entry["detail"] = ((entry.get("detail") or "") + "\n\n" + text).strip()

    # -- the judgement --------------------------------------------------

    def matters(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Does this Activity event deserve a line? Usually not.

        Every rule here is a deliberate answer to "would the owner want to
        find this tomorrow". Success at something they asked for and watched
        happen is not; they were there. What survives is failure, and the
        arrival and departure of things that go on existing afterwards.
        """
        event = message.get("event") or ""
        activity = message.get("activity") or {}
        kind = activity.get("kind") or ""
        state = activity.get("state") or ""
        label = activity.get("label") or "something"
        source = activity.get("source") or "resident"

        # Failure, of anything. The single most useful thing this pane holds:
        # the Resident may well have recovered and moved on without ever
        # saying so plainly, and the owner is owed a way to find out that it
        # had to.
        if state == "failed":
            return {
                "summary": f"{label} failed",
                "detail": _what_happened(activity),
                "level": CONCERN,
                "kind": kind or "tool",
                "source": source,
                "activity_id": activity.get("id"),
            }

        if state == "timed_out":
            return {
                "summary": f"{label} ran out of time",
                "detail": _what_happened(activity),
                "level": CONCERN,
                "kind": kind or "tool",
                "source": source,
                "activity_id": activity.get("id"),
            }

        if state == "cancelled":
            # The owner pressed Stop. Worth a line: a conversation that ends
            # mid-job otherwise looks identical to one that finished.
            return {
                "summary": f"{label} was stopped",
                "level": NOTE,
                "kind": kind or "tool",
                "source": source,
                "activity_id": activity.get("id"),
            }

        # A worker finishing. Delegated work is the case where the owner was
        # least present -- they asked the Resident, the Resident asked someone
        # else, and what came back was a summary. So the fact that it happened
        # at all is worth keeping even when it went fine.
        if kind == "worker" and state == "completed" and event == "completed":
            return {
                "summary": f"{label} finished",
                "detail": activity.get("summary") or "",
                "level": NOTE,
                "kind": "worker",
                "source": source,
                "activity_id": activity.get("id"),
            }

        # Something waiting on a person. Nothing enters this state yet -- it
        # is where the approval modes will land -- but a request that sat
        # unanswered is precisely the kind of thing that should be findable
        # afterwards rather than lost with the runtime.
        if state == "waiting":
            return {
                "summary": f"{label} is waiting",
                "detail": activity.get("detail") or "",
                "level": CONCERN,
                "kind": kind or "tool",
                "source": source,
                "activity_id": activity.get("id"),
            }

        return None
