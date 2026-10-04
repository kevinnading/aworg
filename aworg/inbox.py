"""What AWORG has to tell the Resident, held until it is free to hear it.

Worker replies and Living Log reports arrive whenever they happen; the
Resident can only be told between turns. So they queue here, and the queue
delivers them together, as one message, once the Resident has been idle for
IDLE seconds -- long enough that an owner who has just read a reply and is
typing the next message gets there first.

Each item can say whether it still matters. One the Resident dealt with
while it waited -- a worker it already read, a log entry already resolved --
is dropped at delivery rather than told twice.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass, field
from typing import Any, Callable

#: How long the Resident must have been idle before the queue speaks.
IDLE = 5.0

#: How often the queue checks.
TICK = 1.0


@dataclass
class Item:
    #: Same key, same news: a second put replaces the first.
    key: str
    #: The words, or a function giving them at delivery, so the news is as
    #: of when it is told rather than when it happened.
    text: str | Callable[[], str]
    #: False once the news is stale, checked at delivery.
    relevant: Callable[[], bool] = field(default=lambda: True)
    #: Items in one group share a header, said once before the first of them.
    group: str = ""

    def words(self) -> str:
        return self.text() if callable(self.text) else self.text


class Inbox:
    def __init__(self, resident: Any):
        self.resident = resident
        self.items: dict[str, Item] = {}
        #: A line said once before the first item of a group.
        self.headers: dict[str, str] = {}
        #: When the Resident was last seen busy, or the queue last spoke.
        self.busy_at = time.monotonic()

    def put(
        self,
        key: str,
        text: str | Callable[[], str],
        relevant: Callable[[], bool] | None = None,
        group: str = "",
    ) -> None:
        self.items[key] = Item(key, text, relevant or (lambda: True), group)

    async def run(self) -> None:
        """Deliver when there is something to say and nobody is talking."""
        while True:
            await asyncio.sleep(TICK)
            with contextlib.suppress(Exception):
                self.tick()

    def tick(self) -> None:
        now = time.monotonic()
        turn = self.resident.turn
        if turn is not None and not turn.done:
            self.busy_at = now
            return
        # Timed from the moment the last turn ended, not from the tick that
        # noticed, which can be up to TICK later.
        ended = getattr(turn, "finished_at", None)
        if ended is not None:
            self.busy_at = max(self.busy_at, ended)
        if not self.items or now - self.busy_at < IDLE:
            return
        if self.resident.state()["status"] != "present":
            return

        fresh = []
        for item in self.items.values():
            try:
                keep = item.relevant()
            except Exception:                                  # noqa: BLE001
                keep = True
            if keep:
                fresh.append(item)
        self.items.clear()
        if not fresh:
            return

        said, headed = [], set()
        for item in fresh:
            if item.group and item.group not in headed:
                headed.add(item.group)
                if self.headers.get(item.group):
                    said.append(self.headers[item.group])
            said.append(item.words())

        self.busy_at = now
        try:
            self.resident.start_turn("\n\n".join(said), speaker="watch")
        except Exception:                                      # noqa: BLE001
            # Lost a race with the owner. Put it all back for the next quiet.
            for item in fresh:
                self.items.setdefault(item.key, item)
