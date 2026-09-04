"""Runtime and Resident state.

Holds the model connections, the Resident's configuration, and the
conversation. Credentials deliberately live elsewhere (see secrets.py); a
connection record carries only a reference to its credential, never the
credential itself.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS connections (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    provider   TEXT NOT NULL,
    model      TEXT NOT NULL,
    base_url   TEXT,
    tags       TEXT NOT NULL DEFAULT '[]',
    reasoning  TEXT NOT NULL DEFAULT 'auto',
    context    INTEGER,
    enabled    INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS resident (
    id                      INTEGER PRIMARY KEY CHECK (id = 1),
    primary_connection_id   TEXT,
    worker_connection_id    TEXT,
    system_prompt           TEXT NOT NULL DEFAULT '',
    current_conversation_id TEXT,
    updated_at              TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS appearance (
    id         INTEGER PRIMARY KEY CHECK (id = 1),
    preset     TEXT NOT NULL DEFAULT 'midnight',
    overrides  TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS layout (
    id         INTEGER PRIMARY KEY CHECK (id = 1),
    sizes      TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS conversations (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL DEFAULT 'Conversation',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    model_label     TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation
    ON messages (conversation_id, id);

-- What the Resident has been told about the part of the conversation it can
-- no longer see. One row per conversation, rewritten as the window moves on.
--
-- Deliberately not a row in `messages`. The transcript is the record of what
-- happened and everything in it was actually said; this is a model's account
-- of some of it, which is a different kind of thing and must never be read
-- back as though the Resident had said it. `through_id` is how far the
-- account reaches, so the messages after it are never described twice.
CREATE TABLE IF NOT EXISTS recollections (
    conversation_id TEXT PRIMARY KEY,
    summary         TEXT NOT NULL,
    through_id      INTEGER NOT NULL,
    covers          INTEGER NOT NULL DEFAULT 0,
    model_label     TEXT,
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);
"""


#: Previous shipped defaults. A stored prompt matching one of these exactly
#: was written by AWORG and never touched by the owner, so it is safe to
#: bring up to date. Anything else is the owner's and is left alone -- the
#: standing instructions are theirs, and silently rewriting them would be
#: the worst kind of helpfulness.
PREVIOUS_DEFAULT_PROMPTS = ["""You are the Resident of this Aworg.

You are not a chat assistant that appears when summoned and forgets afterward.
You are a persistent inhabitant of this machine. You live here. The owner you
are speaking with installed you, and you will still be here tomorrow, holding
the same conversation and remembering what was decided in it.

At present you can only converse. You have no tools, no workspace access, and
no ability to run anything. That changes in a later milestone, when you are
given a Living Workspace and the ability to act within it. Be straightforward
about that limitation if it comes up rather than implying abilities you do not
yet have.

Speak plainly and directly. The owner may not be a programmer, and should
never need to be one to work with you."""]


DEFAULT_SYSTEM_PROMPT = """You are the Resident of this Aworg.

You are not a chat assistant that appears when summoned and forgets afterward.
You are a persistent inhabitant of this machine. You live here. The owner you
are speaking with installed you, and you will still be here tomorrow, holding
the same conversation and remembering what was decided in it.

You can act on this machine, not only describe it. Use your tools rather than
reasoning about what is probably there: read the file, run the command, look
at what came back. The owner cannot check your work for you, so an answer you
have seen the evidence for is worth far more than one you assembled from
memory.

When a step fails, say so and say what failed. Never call something done that
you have not watched succeed.

Speak plainly and directly. The owner may not be a programmer, and should
never need to be one to work with you."""


class Store:
    def __init__(self, path: Path):
        self.path = path
        self._init()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    #: Columns added after an Aworg may already have a database. CREATE TABLE
    #: IF NOT EXISTS leaves an existing table exactly as it was, so a new
    #: column has to be asked for separately or it silently is not there.
    MIGRATIONS = [
        ("resident", "worker_connection_id", "TEXT"),
        ("connections", "reasoning", "TEXT NOT NULL DEFAULT 'auto'"),
        ("connections", "context", "INTEGER"),
    ]

    def _init(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)
            conn.execute(
                "INSERT INTO resident (id, system_prompt) VALUES (1, ?) "
                "ON CONFLICT(id) DO NOTHING",
                (DEFAULT_SYSTEM_PROMPT,),
            )
            conn.execute(
                "INSERT INTO appearance (id) VALUES (1) ON CONFLICT(id) DO NOTHING"
            )
            conn.execute(
                "INSERT INTO layout (id) VALUES (1) ON CONFLICT(id) DO NOTHING"
            )
            self._refresh_default_prompt(conn)

    @staticmethod
    def _refresh_default_prompt(conn) -> None:
        """Update standing instructions that AWORG wrote and nobody edited.

        The shipped default described a Resident that could not act, which
        stopped being true the moment it was given tools -- and a model
        obeying it will refuse to use them, which is exactly what happened.

        Only an exact match against a previous default is replaced. A prompt
        the owner has touched, even by a character, is theirs; leaving it
        stale is a smaller wrong than editing it behind their back.
        """
        row = conn.execute("SELECT system_prompt FROM resident WHERE id = 1").fetchone()
        if row is None:
            return
        current = (row["system_prompt"] or "").strip()
        if current and any(current == old.strip() for old in PREVIOUS_DEFAULT_PROMPTS):
            conn.execute(
                "UPDATE resident SET system_prompt = ? WHERE id = 1",
                (DEFAULT_SYSTEM_PROMPT,),
            )

    @classmethod
    def _migrate(cls, conn) -> None:
        """Add any column a newer build expects and an older database lacks.

        Deliberately additive only. An owner's Aworg holds their
        conversation and their configuration; a migration that can drop or
        rewrite either is a migration that can lose them.
        """
        for table, column, decl in cls.MIGRATIONS:
            existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

    # -- recollection ---------------------------------------------------

    def recollection(self, conversation_id: str) -> dict[str, Any] | None:
        """What the Resident has been told about what it can no longer see."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM recollections WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
        return dict(row) if row else None

    def remember(
        self,
        conversation_id: str,
        summary: str,
        through_id: int,
        covers: int,
        model_label: str | None = None,
    ) -> None:
        """Replace the account of the conversation's earlier part.

        Replaced rather than appended: a rolling summary that grows without
        bound is a second conversation, and would push out the real one.
        """
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO recollections "
                "(conversation_id, summary, through_id, covers, model_label, updated_at) "
                "VALUES (?, ?, ?, ?, ?, datetime('now')) "
                "ON CONFLICT(conversation_id) DO UPDATE SET "
                "summary = excluded.summary, through_id = excluded.through_id, "
                "covers = excluded.covers, model_label = excluded.model_label, "
                "updated_at = excluded.updated_at",
                (conversation_id, summary, through_id, covers, model_label),
            )

    def forget(self, conversation_id: str) -> None:
        """Drop the note, when there is no longer anything for it to cover."""
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM recollections WHERE conversation_id = ?",
                (conversation_id,),
            )

    # -- connections ----------------------------------------------------

    def list_connections(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM connections ORDER BY created_at"
            ).fetchall()
        return [self._connection_row(r) for r in rows]

    def get_connection(self, connection_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM connections WHERE id = ?", (connection_id,)
            ).fetchone()
        return self._connection_row(row) if row else None

    def create_connection(
        self,
        name: str,
        provider: str,
        model: str,
        base_url: str | None = None,
        tags: list[str] | None = None,
        reasoning: str = "auto",
        context: int | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        connection_id = uuid.uuid4().hex[:12]
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO connections (id, name, provider, model, base_url, "
                "tags, reasoning, context, enabled) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    connection_id,
                    name,
                    provider,
                    model,
                    base_url or None,
                    json.dumps(tags or []),
                    reasoning,
                    context,
                    1 if enabled else 0,
                ),
            )
        return self.get_connection(connection_id)  # type: ignore[return-value]

    def update_connection(self, connection_id: str, **fields: Any) -> dict[str, Any] | None:
        allowed = {
            "name", "provider", "model", "base_url", "tags", "reasoning", "context", "enabled",
        }
        sets, values = [], []
        for key, value in fields.items():
            if key not in allowed:
                continue
            # None means "not supplied" for every field except the context
            # ceiling, where it is a real value: unknown. Callers clear it
            # by passing 0, which is not a size any model has.
            if key == "context":
                if value is None:
                    continue
                value = None if value == 0 else value
            elif value is None:
                continue
            if key == "tags":
                value = json.dumps(value)
            if key == "enabled":
                value = 1 if value else 0
            sets.append(f"{key} = ?")
            values.append(value)
        if sets:
            sets.append("updated_at = datetime('now')")
            with self._connect() as conn:
                conn.execute(
                    f"UPDATE connections SET {', '.join(sets)} WHERE id = ?",
                    (*values, connection_id),
                )
        return self.get_connection(connection_id)

    def delete_connection(self, connection_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM connections WHERE id = ?", (connection_id,))
            # A deleted connection must not remain the Resident's primary.
            conn.execute(
                "UPDATE resident SET primary_connection_id = NULL "
                "WHERE primary_connection_id = ?",
                (connection_id,),
            )
            conn.execute(
                "UPDATE resident SET worker_connection_id = NULL "
                "WHERE worker_connection_id = ?",
                (connection_id,),
            )

    @staticmethod
    def _connection_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "provider": row["provider"],
            "model": row["model"],
            "base_url": row["base_url"],
            "tags": json.loads(row["tags"]),
            "reasoning": row["reasoning"],
            "context": row["context"],
            "enabled": bool(row["enabled"]),
            "created_at": row["created_at"],
        }

    # -- resident config ------------------------------------------------

    def get_resident(self) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM resident WHERE id = 1").fetchone()
        return {
            "primary_connection_id": row["primary_connection_id"],
            "worker_connection_id": row["worker_connection_id"],
            "system_prompt": row["system_prompt"],
            "current_conversation_id": row["current_conversation_id"],
        }

    def update_resident(self, **fields: Any) -> dict[str, Any]:
        allowed = {
            "primary_connection_id",
            "worker_connection_id",
            "system_prompt",
            "current_conversation_id",
        }
        sets, values = [], []
        for key, value in fields.items():
            if key not in allowed:
                continue
            sets.append(f"{key} = ?")
            values.append(value)
        if sets:
            sets.append("updated_at = datetime('now')")
            with self._connect() as conn:
                conn.execute(f"UPDATE resident SET {', '.join(sets)} WHERE id = 1", values)
        return self.get_resident()

    # -- appearance -----------------------------------------------------

    def get_appearance(self) -> dict[str, Any]:
        """The owner's chosen scheme: a preset, plus any colours they changed.

        Kept in state.db rather than the browser. An Aworg is a place the owner
        returns to, and it should look the way they left it whichever browser
        they open it from.
        """
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM appearance WHERE id = 1").fetchone()
        try:
            overrides = json.loads(row["overrides"])
        except (ValueError, TypeError):
            overrides = {}
        return {
            "preset": row["preset"],
            "overrides": overrides if isinstance(overrides, dict) else {},
        }

    def update_appearance(
        self,
        preset: str | None = None,
        overrides: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        sets, values = [], []
        if preset is not None:
            sets.append("preset = ?")
            values.append(preset)
        if overrides is not None:
            sets.append("overrides = ?")
            values.append(json.dumps(overrides))
        if sets:
            sets.append("updated_at = datetime('now')")
            with self._connect() as conn:
                conn.execute(f"UPDATE appearance SET {', '.join(sets)} WHERE id = 1", values)
        return self.get_appearance()

    # -- layout ---------------------------------------------------------

    def get_layout(self) -> dict[str, int]:
        """The sizes the owner has dragged panes to. Empty means untouched."""
        with self._connect() as conn:
            row = conn.execute("SELECT sizes FROM layout WHERE id = 1").fetchone()
        try:
            sizes = json.loads(row["sizes"])
        except (ValueError, TypeError):
            sizes = {}
        return sizes if isinstance(sizes, dict) else {}

    def update_layout(self, sizes: dict[str, int]) -> dict[str, int]:
        """Replace the stored sizes outright.

        Replacing rather than merging is what makes resetting the view a
        matter of storing nothing, instead of storing the defaults back and
        hoping they still match what the defaults are.
        """
        with self._connect() as conn:
            conn.execute(
                "UPDATE layout SET sizes = ?, updated_at = datetime('now') WHERE id = 1",
                (json.dumps(sizes),),
            )
        return self.get_layout()

    # -- conversation ---------------------------------------------------

    def current_conversation_id(self) -> str:
        """The one ongoing conversation, created the first time it is needed.

        There is exactly one, and nothing ends it. Restarting AWORG returns
        the owner to it rather than to a blank slate, and no button offers to
        start over -- that continuity is most of what makes the Resident feel
        resident rather than summoned.

        A Resident that can be reset to a stranger is not one anybody would
        leave running on their machine for a year.
        """
        resident = self.get_resident()
        if resident["current_conversation_id"]:
            return resident["current_conversation_id"]
        return self._begin_conversation()

    def _begin_conversation(self) -> str:
        """Create the conversation. Called once in an Aworg's life.

        Private because nothing should be able to reach past the ongoing
        conversation and replace it. When casual chats arrive they will be
        their own thing alongside this one, not a way to end it.
        """
        conversation_id = uuid.uuid4().hex[:12]
        with self._connect() as conn:
            conn.execute("INSERT INTO conversations (id) VALUES (?)", (conversation_id,))
            conn.execute(
                "UPDATE resident SET current_conversation_id = ? WHERE id = 1",
                (conversation_id,),
            )
        return conversation_id

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        model_label: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO messages (conversation_id, role, content, model_label) "
                "VALUES (?, ?, ?, ?)",
                (conversation_id, role, content, model_label),
            )

    def messages(self, conversation_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                # The id comes back because summarising has to record how
                # far it has read; nothing else uses it, and it is harmless
                # to the callers that ignore it.
                "SELECT id, role, content, model_label, created_at FROM messages "
                "WHERE conversation_id = ? ORDER BY id",
                (conversation_id,),
            ).fetchall()
        return [dict(r) for r in rows]
