"""Staying inside a provider's tokens-per-minute allowance.

A hosted model is sold by the minute as well as by the token. Cross the line
and the provider refuses the request outright -- and it refuses it in the
middle of a turn, after the Resident has read three files and delegated to a
worker, so the cost of finding out is everything that had been done so far.

That happened, and the way it presented is the reason this file exists rather
than a note in the docs. The turn died on a 429, AWORG recorded nothing, and
the owner was left with a conversation that simply stopped after a tool
result. They waited, typed "continue", and it carried on. Nothing about that
told them what had gone wrong.

So there are two halves here and both matter.

**Staying inside it.** A budget per connection, spent down as requests go out
and refilled by the passage of time. When the next request will not fit, the
caller waits for room instead of being refused -- and is told it is waiting,
because a Resident that goes quiet for forty seconds is indistinguishable
from one that has hung.

**Surviving it anyway.** The budget is an estimate against a number the
provider counts differently, and several Aworgs may share a key. So a 429 is
expected rather than exceptional: it is waited out and retried, not raised.
An allowance that is merely usually respected is one the owner still cannot
leave running overnight.

The window is a real sliding one rather than a fixed bucket. A fixed bucket
lets a minute's worth of tokens go out in the last second of one window and
again in the first second of the next, which is exactly the burst a provider
counts as a violation.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any


#: The span a provider's allowance is measured over.
WINDOW = 60.0

#: How much of the stated allowance to actually use.
#:
#: Not timidity. The count AWORG makes is an estimate from characters, the
#: provider counts real tokens with its own tokenizer, and the reply is
#: charged too but cannot be known before it arrives. Spending the last tenth
#: of a limit computed this loosely is how a limiter that "works" still gets
#: the occasional 429.
HEADROOM = 0.9

#: Longest a single wait may be before giving up and letting the request
#: through. A wait longer than this means the allowance cannot fit the
#: request at all, and sitting on it forever would be a Resident that never
#: answers rather than one that is rate limited.
MAX_WAIT = 90.0


class Budget:
    """One connection's tokens-per-minute allowance, shared by all its users.

    Shared deliberately: the Resident and every worker on the same connection
    spend from the same allowance, because the provider counts them together.
    A per-caller budget would be several callers each politely staying inside
    a limit they are collectively blowing through.
    """

    def __init__(self, limit: int | None):
        #: Tokens per minute, or None for no limit -- which is the right
        #: default for a local model, where the only cost is the owner's own
        #: hardware and a ceiling would be an invention.
        self.limit = limit if limit and limit > 0 else None
        self._spent: deque[tuple[float, int]] = deque()
        #: One waiter at a time. Without it, ten concurrent requests each
        #: compute the same delay, all sleep it, and all wake together to
        #: blow the limit in the same instant.
        self._gate = asyncio.Lock()

    # -- accounting -----------------------------------------------------

    def _prune(self, now: float) -> None:
        while self._spent and now - self._spent[0][0] >= WINDOW:
            self._spent.popleft()

    def used(self) -> int:
        now = time.monotonic()
        self._prune(now)
        return sum(tokens for _, tokens in self._spent)

    def spend(self, tokens: int) -> None:
        """Record tokens as sent. Called whether or not anyone waited."""
        if self.limit is None:
            return
        self._spent.append((time.monotonic(), max(0, int(tokens))))

    def wait_for(self, tokens: int) -> float:
        """Seconds until this request would fit. Zero if it fits now."""
        if self.limit is None:
            return 0.0
        allowance = int(self.limit * HEADROOM)
        now = time.monotonic()
        self._prune(now)
        used = sum(t for _, t in self._spent)
        if used + tokens <= allowance:
            return 0.0

        # Enough of the oldest spending has to age out for this to fit. Walk
        # forward through the window until it does, and wait for that moment
        # rather than for a whole window -- the difference between a pause of
        # four seconds and one of sixty.
        needed = used + tokens - allowance
        freed = 0
        for stamp, amount in self._spent:
            freed += amount
            if freed >= needed:
                return max(0.0, WINDOW - (now - stamp))
        return WINDOW

    # -- using ----------------------------------------------------------

    async def reserve(self, tokens: int, on_wait: Any = None) -> None:
        """Wait until this request fits, then record it as spent.

        `on_wait` is called once with the number of seconds, if there is a
        wait. It is how the owner finds out that nothing is broken -- a
        Resident silent for forty seconds and a Resident that has hung look
        identical from outside, and only one of them is fine.
        """
        if self.limit is None:
            return
        async with self._gate:
            delay = self.wait_for(tokens)
            if delay > 0:
                if on_wait is not None:
                    on_wait(min(delay, MAX_WAIT))
                await asyncio.sleep(min(delay, MAX_WAIT))
            self.spend(tokens)


#: Budgets by connection id. Module level because a connection's allowance
#: belongs to the connection, and the Resident, its workers and anything else
#: reaching the same endpoint have to spend from one pot to stay inside it.
_BUDGETS: dict[str, Budget] = {}


def budget_for(connection_id: str, limit: int | None) -> Budget:
    """The budget for this connection, made once and kept.

    The limit is re-read each time so that an owner raising it in Settings
    takes effect on the next request rather than the next restart, which is
    the same rule capabilities and skills already follow.
    """
    found = _BUDGETS.get(connection_id)
    if found is None:
        found = _BUDGETS[connection_id] = Budget(limit)
    else:
        found.limit = limit if limit and limit > 0 else None
    return found


def forget_all() -> None:
    """Drop every budget. For a factory reset and for tests."""
    _BUDGETS.clear()
