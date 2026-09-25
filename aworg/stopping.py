"""Knowing that this Aworg has been asked to stop.

A module of its own because everything that needs it would otherwise import
something that imports it back: the server holds the Activity feed, the
Resident holds a turn's stream, and the CLI is what learns about the signal
first. One flag, no cycle.

**Why a flag at all.** Two of AWORG's responses never end by themselves --
the Activity feed waits on a queue for as long as a browser is open, and a
turn's stream lives as long as the turn. Shutdown therefore waited the whole
graceful timeout and then cancelled them, and a cancelled StreamingResponse
is not quiet: starlette is sitting inside `listen_for_disconnect` waiting on
receive() at that moment, and uvicorn reports the CancelledError as
"Exception in ASGI application" over forty lines of traceback, on top of a
shutdown that had in fact gone perfectly.

A generator that returns does not have to be cancelled. So they watch this,
finish their responses properly, and an Aworg stops in the time it takes to
close a socket.

Set from the signal handler, which is the earliest anything knows -- before
uvicorn has begun refusing connections, and long before the lifespan's
shutdown runs, which is far too late to help.
"""

from __future__ import annotations

import asyncio
from typing import Any


#: True once this Aworg has been asked to stop. Never cleared: a process
#: that has begun stopping does not change its mind, and an Aworg that
#: starts again is a new process with a new flag.
STOPPING = asyncio.Event()


def asked_to_stop() -> None:
    """Say so. Safe to call more than once, and from a signal handler."""
    STOPPING.set()


async def next_or_stop(queue: asyncio.Queue) -> Any:
    """The next item off the queue, or None if the Aworg is stopping.

    A race rather than a poll, so an idle feed costs nothing at all and a
    shutdown is noticed the instant it begins.

    None is already how both callers hear "there is nothing more coming",
    so a stopping Aworg needs no second signal to mean the same thing.
    """
    getter = asyncio.ensure_future(queue.get())
    stopping = asyncio.ensure_future(STOPPING.wait())
    try:
        done, _ = await asyncio.wait(
            (getter, stopping), return_when=asyncio.FIRST_COMPLETED
        )
        return getter.result() if getter in done else None
    finally:
        # Both are cancelled either way. The loser is waiting on something
        # that will not arrive, and a queue.get() left pending would take
        # an item nobody reads.
        for task in (getter, stopping):
            if not task.done():
                task.cancel()
