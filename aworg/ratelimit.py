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
import re
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
        #: What Settings (or the provider profile) asked for, as opposed to
        #: what is in force. Kept so that a rebuild can tell "the owner
        #: changed this" from "the same value arrived again"; see budget_for.
        self.configured = limit
        self._spent: deque[tuple[float, int]] = deque()
        #: Whether the limit came from the provider rather than from a
        #: default. A stated limit is used as given; a guessed one keeps its
        #: headroom, because a guess that is too high is a guess that gets
        #: the request refused.
        self.stated = False
        #: When the provider says the allowance comes back, as a monotonic
        #: moment. None until a response has said. See observe.
        self.refills_at: float | None = None
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
        """Seconds until this request would fit. Zero if it fits now.

        **Every limit here is now one somebody actually asserted** -- the
        provider on a response header, or the owner in Settings. The profile
        defaults are no longer used as a fallback; see build_adapter. So
        there is nothing left to be timid about, and the headroom that
        existed to soften a guess only applies where the figure is still an
        estimate rather than the provider's own.
        """
        if self.limit is None:
            return 0.0
        allowance = self.limit if self.stated else int(self.limit * HEADROOM)

        # A request larger than the whole allowance can never be made to fit,
        # because waiting frees at most one window's worth. Waiting on it is
        # a minute spent to arrive at the same place, so it goes now and the
        # provider decides -- and a 429 is already waited out and retried.
        #
        # This was not theoretical. Every session began against the default
        # limit, before any response had corrected it, and the first request
        # of a long conversation is far bigger than that default: 222,000
        # tokens against an assumed 30,000. So each session opened by sleeping
        # a full minute for nothing.
        if tokens > allowance:
            return 0.0

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
        computed = WINDOW
        for stamp, amount in self._spent:
            freed += amount
            if freed >= needed:
                computed = max(0.0, WINDOW - (now - stamp))
                break

        # The provider's own answer beats the one worked out here, and it is
        # usually far shorter. What is computed above assumes the spending
        # happened when it was recorded; after `observe` that is one lump
        # stamped now, so it always says a whole window. The reset header
        # says when the allowance actually returns.
        if self.refills_at is not None:
            return max(0.0, min(computed, self.refills_at - now))
        return computed

    # -- what the provider says -----------------------------------------

    def observe(self, headers: Any) -> None:
        """Adopt the provider's own accounting, which beats any guess.

        **This is the part that makes the limit right rather than cautious.**
        A default is a guess about somebody else's tier, and the guess here
        was 30,000 -- which on a long conversation, where a single request
        carries twenty thousand tokens of history, allowed about one request
        a minute. A turn that made twelve tool calls waited sixty seconds
        twelve times: thirteen minutes to do a minute of work, obeying a
        limit the provider may never have had.

        OpenAI states the real figures on every response. Reading them turns
        the guess into an observation on the first request, and `remaining`
        is better than anything counted here -- it is the provider's own
        tally, of its own tokens, including the replies that could not be
        counted in advance.
        """
        limit = _header_int(headers, "x-ratelimit-limit-tokens")
        if limit:
            self.limit = limit
            self.stated = True

        remaining = _header_int(headers, "x-ratelimit-remaining-tokens")
        if remaining is not None and self.limit:
            # Replace the local tally rather than adjusting it. What is left
            # is a fact; what has been spent is arithmetic on an estimate.
            spent = max(0, self.limit - remaining)
            self._spent.clear()
            self._spent.append((time.monotonic(), spent))

        # **When the allowance comes back, in the provider's own words.**
        #
        # Without this the tally above is one lump stamped now, so nothing
        # can age out of the sliding window before a full minute has passed
        # and any wait computed from it is sixty seconds. The provider
        # meanwhile says the real answer on the same response -- and on the
        # 429 it says it in words: "Please try again in 4.381s". Waiting a
        # minute when the answer was four seconds is fifty-six seconds of an
        # owner watching nothing.
        #
        # Kept as a moment rather than a duration, because it is read later
        # than it arrives.
        reset = _header_seconds(headers, "x-ratelimit-reset-tokens")
        self.refills_at = time.monotonic() + reset if reset is not None else None

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


#: How OpenAI writes a duration in its rate-limit headers: "6m0s",
#: "4.381s", "128ms", sometimes several parts together. Not a plain number
#: of seconds, which is why it needs its own reader rather than _header_int.
_DURATION = re.compile(r"([0-9]*\.?[0-9]+)\s*(ms|s|m|h)", re.I)

_IN_SECONDS = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}


def _header_seconds(headers: Any, name: str) -> float | None:
    """A duration header, in seconds. None if absent or unreadable.

    Sums every part, so "6m0s" is 360 and "1m30s" is 90. A header that
    cannot be read is treated as one that was not sent -- a limiter that
    guessed at a malformed duration would be inventing the very number this
    exists to stop inventing.
    """
    try:
        raw = (headers.get(name) or "").strip()
    except Exception:                                      # noqa: BLE001
        return None
    if not raw:
        return None
    parts = _DURATION.findall(raw)
    if not parts:
        # A bare number is seconds, which is what most providers send.
        try:
            return max(0.0, float(raw))
        except ValueError:
            return None
    return max(0.0, sum(float(n) * _IN_SECONDS[u.lower()] for n, u in parts))


def _header_int(headers: Any, name: str) -> int | None:
    """One of the provider's rate-limit headers, as a number.

    Absent or unparseable means the provider did not say, which is the
    ordinary case for everything that is not OpenAI.
    """
    try:
        raw = (headers.get(name) or "").strip()
    except Exception:                                      # noqa: BLE001
        return None
    if not raw:
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


#: Budgets by connection id. Module level because a connection's allowance
#: belongs to the connection, and the Resident, its workers and anything else
#: reaching the same endpoint have to spend from one pot to stay inside it.
_BUDGETS: dict[str, Budget] = {}


def budget_for(connection_id: str, limit: int | None) -> Budget:
    """The budget for this connection, made once and kept.

    **A configured limit only replaces the current one when it has actually
    changed.** The obvious version reassigned on every call, so that an owner
    raising the figure in Settings took effect immediately -- and it also
    undid, on every single turn, whatever the provider had told us.

    That was the whole fix defeating itself. An adapter is rebuilt for every
    turn and every worker, so the real limit learned from a response header
    survived exactly until the next request was prepared, and the Resident
    went on waiting against a default sixteen times too low.

    So the configured figure is remembered, and only a change to it is
    allowed to overwrite. An owner editing Settings still takes effect on the
    next request; a rebuild with the same setting leaves what was learned
    alone.
    """
    found = _BUDGETS.get(connection_id)
    if found is None:
        return _BUDGETS.setdefault(connection_id, Budget(limit))
    if limit != found.configured:
        found.configured = limit
        found.limit = limit if limit and limit > 0 else None
        found.stated = False
    return found


def forget_all() -> None:
    """Drop every budget. For a factory reset and for tests."""
    _BUDGETS.clear()
