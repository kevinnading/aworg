"""Looking at the Living Log on a schedule, and noticing what is outstanding.

The MVP spec asks that AWORG "periodically examines unresolved ones". This is
that, and deliberately only that: it looks, it holds what it found, and it
hands it to whoever is listening. It does not diagnose, does not decide, and
does not repair.

**The restraint is the design.** What comes next is the autonomous repair
loop, and the temptation will be to grow it here -- a little triage, then a
little investigation, then a little fixing, until the thing that notices and
the thing that acts are one object nobody can reason about separately. So the
seam exists before the thing that uses it: `on_trouble` is called with what
was found, and everything about what to do belongs on the far side of it.

That separation buys two things beyond tidiness. The inspection can be tested
without a model attached, and an owner can eventually turn repair off while
leaving noticing on -- which is the difference between an Aworg that will not
fix things and an Aworg that cannot see them.

Nothing here writes to the Living Log on a routine pass. A log that gains an
entry every minute saying it was read is a log nobody reads, and this pane's
whole value is that everything in it is worth the space.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any


#: How often to look. A minute is far too often for a person and about right
#: for a machine: long enough that an idle Aworg costs nothing, short enough
#: that an application which fell over at three in the morning is noticed at
#: 03:01 rather than at breakfast.
#:
#: Not configurable yet, on purpose. The number that matters is the one the
#: repair loop will want, and picking it before there is a repair loop to
#: measure would be guessing in public.
INTERVAL = 60.0

#: Ignore trouble younger than this on the first sighting.
#:
#: An application often reports a failure at the very moment the Resident is
#: already dealing with it -- a tool call that failed and was retried is in
#: the log within a second of the retry succeeding. Letting something sit
#: briefly before treating it as outstanding is what keeps a watcher from
#: interrupting work that is already in hand.
SETTLE = 30.0


class Watch:
    """Reads the Living Log on a schedule and says what is still open.

    Runtime state, like the Activity Manager and for the same reason: "when
    did you last look" has no meaning across a restart, and an Aworg that has
    just started has not looked yet however long its log is.
    """

    def __init__(self, journal: Any, on_trouble: Any = None):
        self.journal = journal
        #: Called with the list of outstanding entries whenever a pass finds
        #: any. The repair loop's attachment point, and the only thing here
        #: that knows anything happens afterwards.
        self.on_trouble = on_trouble
        #: When this Aworg started watching, and when it last looked. Both,
        #: because "inspection is running" and "inspection has actually run"
        #: are different claims and the Lifecycle stepper needs the second.
        self.started_at: float | None = None
        self.last_looked: float | None = None
        self.outstanding: list[dict[str, Any]] = []
        #: How many passes have run. Cheap, and it is the thing that makes
        #: "being inspected" checkable rather than assertable.
        self.passes = 0

    # -- the pass -------------------------------------------------------

    async def inspect(self) -> list[dict[str, Any]]:
        """Look once. Returns what is outstanding.

        Everything unresolved, not only what is new. A problem that has been
        open for an hour is still a problem, and a watcher that reported only
        changes would go quiet about an outage precisely because it had
        already mentioned it.
        """
        found = self.journal.open_entries()
        self.last_looked = time.time()
        self.passes += 1

        # Settled ones only. Something that failed two seconds ago may well
        # be being dealt with by the turn that caused it.
        ripe = [e for e in found if self._settled(e)]
        self.outstanding = ripe

        if ripe and self.on_trouble is not None:
            try:
                result = self.on_trouble(ripe)
                if asyncio.iscoroutine(result):
                    await result
            except asyncio.CancelledError:
                raise
            except Exception:                              # noqa: BLE001
                # Whatever acts on trouble failing must not stop the noticing.
                # An Aworg that stopped looking because its repairs threw
                # would go blind at exactly the moment it mattered.
                pass
        return ripe

    async def run(self) -> None:
        """Look now, then every INTERVAL, until cancelled.

        Now rather than after the first interval, and it matters in the case
        this exists for. An Aworg that was restarted -- or that crashed and
        came back -- may have an application that fell over while it was
        away, and a watcher that waited a minute before its first look would
        be blind across exactly the gap it is meant to cover. It would also
        report "not inspected" for that minute, which is true and useless.
        """
        self.started_at = time.time()
        try:
            await self.inspect()
            while True:
                await asyncio.sleep(INTERVAL)
                await self.inspect()
        except asyncio.CancelledError:
            raise
        finally:
            self.started_at = None

    # -- what the interface and the stepper need -------------------------

    def snapshot(self) -> dict[str, Any]:
        return {
            "watching": self.started_at is not None,
            "started_at": self.started_at,
            "last_looked": self.last_looked,
            "passes": self.passes,
            "outstanding": len(self.outstanding),
            "entries": self.outstanding,
        }

    @staticmethod
    def _settled(entry: dict[str, Any]) -> bool:
        """Whether this has been open long enough to count as outstanding."""
        stamp = entry.get("at") or ""
        moment = _parse(stamp)
        if moment is None:
            # An entry whose time cannot be read is treated as settled rather
            # than skipped forever. Better to look at it once too early than
            # to have it sit unnoticed because of a format.
            return True
        return (time.time() - moment) >= SETTLE


def _parse(stamp: str) -> float | None:
    """SQLite's datetime('now'), which is UTC, as a timestamp.

    Written out rather than left to fromisoformat alone because the value has
    no timezone on it and is not local: read naively it is wrong by whatever
    the machine's offset happens to be, which on this one would make every
    entry look several hours old and settle instantly.
    """
    from datetime import datetime, timezone

    with contextlib.suppress(ValueError):
        return (
            datetime.fromisoformat(stamp)
            .replace(tzinfo=timezone.utc)
            .timestamp()
        )
    return None
