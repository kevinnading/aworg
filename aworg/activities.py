"""Activities: what AWORG is doing right now.

Three different questions, kept apart deliberately:

    Tasks         what should be accomplished
    Activities    what is happening at this moment
    Living Log    what happened, and mattered

An Activity is a runtime object rather than a callback. Something starts one,
it moves through a lifecycle, and it emits an event at every transition.
Whoever cares subscribes. The manager itself decides nothing -- not what to
run next, not what is worth remembering. It tracks and it emits; subscribers
decide what that means.

That separation is the whole design. A tool call that notified the interface
directly, and the Living Log directly, and its caller directly, would have to
know about all three. It knows about none of them, and gains a fourth
subscriber without being touched.

Activities are runtime state and do not survive a restart. What the model was
shown lives in the conversation, which is permanent; an Activity holds the
full evidence behind that while the Aworg is up. Losing evidence depth on
restart is a real cost, and the fix is persistence rather than moving the
payload into the conversation -- the conversation records what was said.
"""

from __future__ import annotations

import asyncio
import itertools
import time
import uuid
from typing import Any


#: Lifecycle states. The first four are the ordinary path; the last four are
#: terminal, and three of them are ways of not succeeding.
CREATED = "created"
QUEUED = "queued"
RUNNING = "running"
WAITING = "waiting"
COMPLETED = "completed"
FAILED = "failed"
CANCELLED = "cancelled"
TIMED_OUT = "timed_out"

TERMINAL = frozenset({COMPLETED, FAILED, CANCELLED, TIMED_OUT})


class Activity:
    """One piece of work, observable while it happens.

    Carries two records of its result, and the difference between them is the
    point. `summary` is what the caller was shown -- sized to fit a context
    window, and stored in the conversation because it is what was said.
    `payload` is the whole of what actually came back, kept here as evidence
    for an owner who wants to see for themselves.
    """

    def __init__(
        self,
        kind: str,
        label: str,
        source: str = "resident",
        parent_id: str | None = None,
        detail: str = "",
    ):
        self.id = uuid.uuid4().hex[:12]
        #: What sort of work this is -- "tool" today, more later. The
        #: interface groups on it; nothing branches on it.
        self.kind = kind
        #: Short human phrase, shown in the Activities panel as-is.
        self.label = label
        #: Who owns this: "resident", or a worker's id once workers exist.
        self.source = source
        self.parent_id = parent_id
        self.detail = detail

        self.state = CREATED
        self.created_at = time.time()
        self.started_at: float | None = None
        self.ended_at: float | None = None
        #: 0.0-1.0 where a job can say, None where it cannot. Most cannot,
        #: and inventing a number for them would be a progress bar that lies.
        self.progress: float | None = None
        self.summary: str = ""
        self.payload: Any = None
        self.error: str | None = None

    @property
    def duration(self) -> float | None:
        if self.started_at is None:
            return None
        return (self.ended_at or time.time()) - self.started_at

    @property
    def finished(self) -> bool:
        return self.state in TERMINAL

    def snapshot(self) -> dict[str, Any]:
        """What a subscriber sees. Never the payload: it may be enormous.

        The interface asks for a payload by id when the owner opens one,
        rather than every subscriber carrying megabytes of command output
        through a websocket to display forty characters of it.
        """
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "source": self.source,
            "parent_id": self.parent_id,
            "detail": self.detail,
            "state": self.state,
            "progress": self.progress,
            "summary": self.summary,
            "error": self.error,
            "duration": self.duration,
            "created_at": self.created_at,
            "has_payload": self.payload is not None,
        }


class ActivityManager:
    """Tracks Activities and announces what happens to them.

    Deliberately without opinions. It will not start work, will not decide
    what runs next, and will not judge that something deserves a place in the
    Living Log. Every one of those is a subscriber's job, and keeping them out
    of here is what stops this becoming the place all behaviour accumulates.
    """

    #: How many finished Activities to keep. Running ones are never dropped
    #: however many there are -- a cap that could evict live work would make
    #: the panel lie about what is happening.
    HISTORY = 200

    def __init__(self) -> None:
        self._activities: dict[str, Activity] = {}
        self._order: list[str] = []
        self._subscribers: set[asyncio.Queue] = set()
        self._counter = itertools.count()

    # -- lifecycle ------------------------------------------------------

    def create(
        self,
        kind: str,
        label: str,
        source: str = "resident",
        parent_id: str | None = None,
        detail: str = "",
    ) -> Activity:
        activity = Activity(kind, label, source, parent_id, detail)
        self._activities[activity.id] = activity
        self._order.append(activity.id)
        self._prune()
        self._emit("created", activity)
        return activity

    def queued(self, activity: Activity) -> None:
        self._transition(activity, QUEUED, "queued")

    def started(self, activity: Activity) -> None:
        activity.started_at = time.time()
        self._transition(activity, RUNNING, "started")

    def waiting(self, activity: Activity, detail: str = "") -> None:
        if detail:
            activity.detail = detail
        self._transition(activity, WAITING, "waiting")

    def progress(
        self, activity: Activity, fraction: float | None = None, detail: str = ""
    ) -> None:
        """A running job saying it has got somewhere.

        Not a state change -- an Activity reporting progress is still
        running -- so this emits without touching `state`.
        """
        if fraction is not None:
            activity.progress = max(0.0, min(1.0, fraction))
        if detail:
            activity.detail = detail
        self._emit("progress", activity)

    def completed(self, activity: Activity, summary: str = "", payload: Any = None) -> None:
        activity.summary = summary
        activity.payload = payload
        self._finish(activity, COMPLETED, "completed")

    def failed(self, activity: Activity, error: str, payload: Any = None) -> None:
        activity.error = error
        activity.payload = payload
        self._finish(activity, FAILED, "failed")

    def cancelled(self, activity: Activity) -> None:
        self._finish(activity, CANCELLED, "cancelled")

    def timed_out(self, activity: Activity, error: str = "") -> None:
        activity.error = error or "Timed out."
        self._finish(activity, TIMED_OUT, "timed_out")

    def _finish(self, activity: Activity, state: str, event: str) -> None:
        activity.ended_at = time.time()
        self._transition(activity, state, event)

    def _transition(self, activity: Activity, state: str, event: str) -> None:
        activity.state = state
        self._emit(event, activity)

    # -- subscription ---------------------------------------------------

    def _emit(self, event: str, activity: Activity) -> None:
        message = {
            "seq": next(self._counter),
            "event": event,
            "activity": activity.snapshot(),
        }
        for queue in list(self._subscribers):
            queue.put_nowait(message)

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    # -- reading --------------------------------------------------------

    def get(self, activity_id: str) -> Activity | None:
        return self._activities.get(activity_id)

    def live(self) -> list[dict[str, Any]]:
        """Everything not yet finished, oldest first."""
        return [
            self._activities[i].snapshot()
            for i in self._order
            if not self._activities[i].finished
        ]

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        """The latest Activities whatever their state, newest last."""
        chosen = self._order[-limit:]
        return [self._activities[i].snapshot() for i in chosen]

    def children(self, parent_id: str) -> list[Activity]:
        return [
            self._activities[i]
            for i in self._order
            if self._activities[i].parent_id == parent_id
        ]

    def _prune(self) -> None:
        """Forget the oldest finished Activities once there are too many.

        Running work is skipped rather than counted, so a burst of concurrent
        jobs cannot push a live one out of the panel it is meant to appear in.
        """
        finished = [i for i in self._order if self._activities[i].finished]
        excess = len(finished) - self.HISTORY
        for activity_id in finished[:max(0, excess)]:
            self._activities.pop(activity_id, None)
            self._order.remove(activity_id)

