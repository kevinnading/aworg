"""The credential store.

Every secret in AWORG passes through this one interface. Nothing else in the
codebase reads or writes a credential directly, and credentials are never
returned to the owner interface once stored -- callers can only ask whether
one exists.

Storage is currently plaintext in a separate database file. That is a
deliberate Milestone 1 choice, not an oversight: the point right now is to
establish the choke point. Swapping the backing store for OS keychain
integration or an encrypted store later is a change to this file alone.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS secrets (
    ref        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class SecretStore:
    def __init__(self, path: Path):
        self.path = path
        self._init()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def set(self, ref: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO secrets (ref, value) VALUES (?, ?) "
                "ON CONFLICT(ref) DO UPDATE SET value=excluded.value, "
                "updated_at=datetime('now')",
                (ref, value),
            )

    def get(self, ref: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM secrets WHERE ref = ?", (ref,)
            ).fetchone()
        return row[0] if row else None

    def has(self, ref: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM secrets WHERE ref = ?", (ref,)
            ).fetchone()
        return row is not None

    def delete(self, ref: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM secrets WHERE ref = ?", (ref,))


def credential_ref(connection_id: str) -> str:
    """The stable reference under which a connection's credential lives."""
    return f"connection:{connection_id}"
