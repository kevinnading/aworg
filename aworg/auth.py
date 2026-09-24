"""The password on the owner interface, and the sessions it grants.

The interface had no authentication at all. That was defensible while an
Aworg only ever listened on 127.0.0.1 -- anything that could reach the port
was already running as the owner -- and it stops being defensible the moment
anyone binds it to a real address, which is exactly what someone putting
AWORG on a home server will do. What is behind the port is a Resident with
filesystem and shell capabilities, so an open one is a shell on that machine.

**One password and no username.** There is one owner. A username field is a
box to fill in that protects nothing and that everybody types the same thing
into.

**Generated rather than chosen**, once, on first start, and printed to the
terminal where the owner is already looking. Owners pick bad passwords, and
generating it means the safe path is also the lazy one. They can change it
afterwards, which is their business.

**Stored as a scrypt hash, never as the password.** `secrets.db` is
deliberately plaintext -- see secrets.py, where that is a recorded Milestone
1 decision rather than an oversight -- so anything kept there is readable by
anyone holding the file. That is survivable for a model credential, which is
useless without the account it belongs to, and not survivable for the key to
the machine. A hash costs nothing, needs no dependency beyond hashlib, and
means the file cannot yield a working password.

The cost of hashing is that a forgotten password cannot be recovered, only
replaced. `aworg password` does that from the terminal, which is the right
place: somebody standing at the machine's command line already has
everything the password protects.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets as secrets_module
import time
from typing import Any


#: Where the hash lives in the credential store, beside the model keys and
#: the Living Log's report token.
REF = "owner:password"

#: The alphabet a generated password is drawn from. No l/1/I, no O/0, and no
#: u/v pair -- it is going to be read off a terminal and typed into a phone,
#: and a character somebody mistypes is a password they believe is broken.
ALPHABET = "abcdefghjkmnpqrstwxyz23456789"

#: Four groups of four. Twenty-eight characters of alphabet across sixteen
#: positions is about seventy-seven bits, which is far past anything that
#: can be guessed against a rate-limited login, and the dashes are what make
#: it possible to read one out loud.
GROUPS, GROUP_SIZE = 4, 4

#: scrypt's cost. About a tenth of a second on an ordinary machine, which is
#: nothing to a person logging in once and a wall to anyone guessing.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1

#: How long a session lasts without being used. Long enough that an owner
#: working through an afternoon is not asked twice, short enough that a
#: browser left open on a shared machine does not stay open forever.
SESSION_IDLE = 12 * 60 * 60

#: What the session cookie is called.
COOKIE = "aworg_session"

#: How many wrong answers before a pause, and how long the pause is.
#:
#: A generated password cannot be guessed. One the owner chose in Settings
#: might be "dog", and this is going to sit on a network, so the limit is
#: about the password they pick rather than the one AWORG gives them.
MAX_ATTEMPTS, LOCKOUT = 5, 60.0


def generate() -> str:
    """A new password, in the form an owner has to be able to type."""
    raw = "".join(
        secrets_module.choice(ALPHABET) for _ in range(GROUPS * GROUP_SIZE)
    )
    return "-".join(
        raw[i:i + GROUP_SIZE] for i in range(0, len(raw), GROUP_SIZE)
    )


def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt,
        n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32,
        # scrypt needs about n * r * 128 bytes; the default ceiling is
        # lower than that at this cost, so it is raised deliberately rather
        # than the cost being lowered to fit it.
        maxmem=64 * 1024 * 1024,
    )


def store(secrets: Any, password: str) -> None:
    """Write the password down as a hash, replacing any there."""
    salt = secrets_module.token_bytes(16)
    secrets.set(REF, f"scrypt${salt.hex()}${_hash(password, salt).hex()}")


def is_set(secrets: Any) -> bool:
    return bool(secrets.get(REF))


def verify(secrets: Any, password: str) -> bool:
    """Whether that is the password. Constant time, and false if none is set.

    An Aworg with no password set refuses every answer rather than accepting
    any. The alternative -- no password means no gate -- is the kind of
    default that is correct until the one time the record is missing.
    """
    held = secrets.get(REF) or ""
    parts = held.split("$")
    if len(parts) != 3 or parts[0] != "scrypt":
        return False
    try:
        salt, expected = bytes.fromhex(parts[1]), bytes.fromhex(parts[2])
    except ValueError:
        return False
    return hmac.compare_digest(_hash(password, salt), expected)


class Sessions:
    """Who is currently signed in.

    In memory, so a restart signs everybody out. That is the right side to
    err on for a single-owner program: the cost is typing a password again
    after an upgrade, and the alternative is a token in the database that
    outlives every reason anyone had to trust it.
    """

    def __init__(self) -> None:
        self.live: dict[str, float] = {}
        #: Wrong answers, by whoever is asking, and when the last one was.
        self.misses: dict[str, tuple[int, float]] = {}

    def open(self) -> str:
        token = secrets_module.token_urlsafe(32)
        self.live[token] = time.time()
        return token

    def valid(self, token: str | None) -> bool:
        if not token:
            return False
        last = self.live.get(token)
        if last is None:
            return False
        if time.time() - last > SESSION_IDLE:
            self.live.pop(token, None)
            return False
        # Touched on use, so an owner working is never signed out mid-job.
        self.live[token] = time.time()
        return True

    def close(self, token: str | None) -> None:
        if token:
            self.live.pop(token, None)

    def close_all(self) -> None:
        """Every session, everywhere. What a password change means."""
        self.live.clear()

    # -- guessing --------------------------------------------------------

    def locked_for(self, who: str) -> float:
        """Seconds this caller must wait, or 0."""
        count, when = self.misses.get(who, (0, 0.0))
        if count < MAX_ATTEMPTS:
            return 0.0
        left = LOCKOUT - (time.time() - when)
        return left if left > 0 else 0.0

    def missed(self, who: str) -> None:
        count, when = self.misses.get(who, (0, 0.0))
        if count >= MAX_ATTEMPTS and time.time() - when > LOCKOUT:
            count = 0                      # served the pause; start again
        self.misses[who] = (count + 1, time.time())

    def hit(self, who: str) -> None:
        self.misses.pop(who, None)
