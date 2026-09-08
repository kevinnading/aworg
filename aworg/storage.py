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
    -- MCP content blocks, as JSON, for a message that is more than prose:
    -- a reply that asked for tools, or the results that answered it. NULL
    -- for the ordinary case, which is most messages and stays a plain
    -- string. See add_message for why both columns exist.
    blocks          TEXT,
    model_label     TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);

CREATE TABLE IF NOT EXISTS workers (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    -- Load-bearing, not decoration. It is the only thing the Resident routes
    -- on when choosing which worker to hand a job to, so a vague one is a
    -- misrouted job the owner experiences as the wrong specialist doing
    -- their work. See docs/06_ARCHITECTURE.md.
    description   TEXT NOT NULL DEFAULT '',
    -- NULL means "whatever the worker connection is set to", which is the
    -- ordinary case: workers share one small model and differ by prompt and
    -- tool scope. A worker may name its own connection when it needs a
    -- bigger mind than its siblings.
    connection_id TEXT,
    system_prompt TEXT NOT NULL DEFAULT '',
    -- JSON list of tool names or capability ids. Empty means every tool the
    -- owner has enabled, which is deliberately not the default: a worker
    -- that cannot write cannot damage the workspace however badly it
    -- misreads its job.
    tools         TEXT NOT NULL DEFAULT '[]',
    enabled       INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS capability_state (
    id         TEXT PRIMARY KEY,
    enabled    INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation
    ON messages (conversation_id, id);

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
never need to be one to work with you.""", """You are the Resident of this Aworg.

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
never need to be one to work with you.""", """You are the Resident of this Aworg.

You are not a chat assistant that appears when summoned and forgets afterward.
You are a persistent inhabitant of this machine. You live here. The owner you
are speaking with installed you, and you will still be here tomorrow, holding
the same conversation and remembering what was decided in it.

At present you can only converse. You cannot run anything, read or write any
file, or act on this machine in any way. Be straightforward about that if it
comes up, rather than implying abilities you do not have or describing what
you would do as though you had done it.

Speak plainly and directly. The owner may not be a programmer, and should
never need to be one to work with you."""]


#: Kept deliberately short. Measured against the models this is developed
#: for, longer system prompts scored *worse* -- see docs/06_ARCHITECTURE.md.
#: Every sentence here is earning its place or should be cut.
DEFAULT_SYSTEM_PROMPT = """You are the Resident of this Aworg.

You are not a chat assistant that appears when summoned and forgets afterward.
You are a persistent inhabitant of this machine. You live here. The owner you
are speaking with installed you, and you will still be here tomorrow, holding
the same conversation and remembering what was decided in it.

You have tools, and you can act on this machine rather than only describe it.
Use them instead of reasoning about what is probably there: read the file, run
the command, look at what came back. Guessing and checking cost you the same
one step, and only one of them is true.

The owner cannot check your work for you. That is the whole reason you are
here, so it matters more than anything else you do: never call something done
that you have not watched succeed, and when a step fails, say plainly that it
failed and what it said. Be clear about the difference between what you have
verified and what you believe. Things going wrong is ordinary -- investigate
and try again, and involve the owner when you are genuinely stuck rather than
merely inconvenienced.

Speak plainly and directly. The owner may not be a programmer, and should
never need to be one to work with you."""


#: The workers a fresh Aworg starts with.
#:
#: Seeded once, when the table is empty, and never again -- an owner who
#: deletes one should not find it back tomorrow.
#:
#: Three, and the number is the point. The Resident routes by picking a name
#: out of this list, and routing degrades as the list grows exactly the way
#: tool selection does. Three specialists whose jobs do not overlap are
#: routed correctly; ten shading into each other are not.
#:
#: Prompts are deliberately short. Measured against the models this is built
#: for, longer system prompts scored *worse* -- see docs/06_ARCHITECTURE.md.
#:
#: Note what each one is *not given*. The builder has no shell, so it cannot
#: run anything however badly it misreads a job. The checker cannot write, so
#: its report cannot be a change it made. That is not trust, it is the tool
#: scope: a worker is not asked to avoid something, it is simply not handed
#: the means.
DEFAULT_WORKERS = [
    {
        "name": "builder",
        "description": (
            "Writes and edits files. Give it what the file should contain "
            "and where it goes. Cannot run anything."
        ),
        "tools": ["read_file", "write_file", "search_files"],
        "system_prompt": (
            "You write files. Do exactly what the task asks and nothing more.\n\n"
            "Write the file, then say in one or two sentences what you wrote "
            "and where. If you could not, say so plainly and say why."
        ),
    },
    {
        "name": "runner",
        "description": (
            "Runs commands and reports exactly what they printed and the "
            "exit code. Cannot write files."
        ),
        "tools": ["execute_command", "read_file"],
        "system_prompt": (
            "You run commands. Run what the task asks, then report exactly "
            "what came back.\n\n"
            "Quote the output rather than summarising it, and always give the "
            "exit code. A command that failed is a normal result: report the "
            "failure, do not try to hide or fix it."
        ),
    },
    {
        "name": "checker",
        "description": (
            "Checks whether something actually works and reports what it "
            "found. Use it to verify work rather than trusting it. Cannot "
            "change anything."
        ),
        "tools": ["read_file", "search_files", "execute_command"],
        "system_prompt": (
            "You check whether something actually works. You did not do the "
            "work and you have no stake in it having gone well.\n\n"
            "Look for yourself: read the file, run the thing, see what it "
            "does. Report what you found, not what was hoped for. Saying "
            "\"this does not work, here is what happened\" is the most useful "
            "thing you can do. Never report success you did not observe."
        ),
    },
]


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
        ("messages", "blocks", "TEXT"),
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
            self._seed_workers(conn)

    @staticmethod
    def _seed_workers(conn) -> None:
        """Put the shipped workers in, once, if there are none at all.

        Only when the table is completely empty. An owner who deleted the
        builder meant to delete it, and finding it back at the next restart
        would be AWORG overruling them about their own machine.
        """
        if conn.execute("SELECT COUNT(*) c FROM workers").fetchone()["c"]:
            return
        for spec in DEFAULT_WORKERS:
            conn.execute(
                "INSERT INTO workers (id, name, description, system_prompt, tools) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    uuid.uuid4().hex[:12],
                    spec["name"],
                    spec["description"],
                    spec["system_prompt"],
                    json.dumps(spec["tools"]),
                ),
            )

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
        blocks: list[dict[str, Any]] | None = None,
    ) -> int:
        """Record one message, and return the row id it was given.

        Two columns hold the content, and they are not redundant. `blocks`
        is the structured truth -- MCP content blocks, which is what a model
        that asked for a tool actually said, and what has to go back to it
        verbatim next turn. `content` is the same thing rendered as prose,
        which is what the interface shows and what the token estimate
        measures.

        Deriving one from the other on every read would be the alternative,
        and it would mean the rendering rules becoming load-bearing for
        anything that counts tokens. Storing both costs a column.

        The row id comes back because a tool exchange is written in two
        steps -- the reply that asked, then the results that answered -- and
        the second has to be able to point at the first.
        """
        payload = json.dumps(blocks) if blocks else None
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO messages "
                "(conversation_id, role, content, blocks, model_label) "
                "VALUES (?, ?, ?, ?, ?)",
                (conversation_id, role, content, payload, model_label),
            )
            return int(cursor.lastrowid)

    def messages(self, conversation_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                # The id comes back because summarising has to record how
                # far it has read; nothing else uses it, and it is harmless
                # to the callers that ignore it.
                "SELECT id, role, content, blocks, model_label, created_at "
                "FROM messages WHERE conversation_id = ? ORDER BY id",
                (conversation_id,),
            ).fetchall()

        out = []
        for row in rows:
            record = dict(row)
            # A row written before this column existed has no blocks, and a
            # row whose JSON is somehow unreadable is treated the same way:
            # as the plain message it also is. Losing the structure degrades
            # the conversation; raising here would lose all of it.
            raw = record.pop("blocks", None)
            try:
                record["blocks"] = json.loads(raw) if raw else None
            except (TypeError, ValueError):
                record["blocks"] = None
            out.append(record)
        return out

    # -- workers --------------------------------------------------------

    def list_workers(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM workers"
                + (" WHERE enabled = 1" if enabled_only else "")
                + " ORDER BY name"
            ).fetchall()
        return [self._worker_row(r) for r in rows]

    def get_worker(self, worker_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM workers WHERE id = ?", (worker_id,)
            ).fetchone()
        return self._worker_row(row) if row else None

    def worker_by_name(self, name: str) -> dict[str, Any] | None:
        """Find a worker the way the Resident names one.

        Matched case-insensitively, because the name travels through a model
        and comes back capitalised however that model felt about it.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM workers WHERE lower(name) = lower(?)", (name.strip(),)
            ).fetchone()
        return self._worker_row(row) if row else None

    def create_worker(
        self,
        name: str,
        description: str = "",
        connection_id: str | None = None,
        system_prompt: str = "",
        tools: list[str] | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        worker_id = uuid.uuid4().hex[:12]
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO workers (id, name, description, connection_id, "
                "system_prompt, tools, enabled) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    worker_id,
                    name,
                    description,
                    connection_id,
                    system_prompt,
                    json.dumps(tools or []),
                    1 if enabled else 0,
                ),
            )
        return self.get_worker(worker_id)  # type: ignore[return-value]

    def update_worker(self, worker_id: str, **fields: Any) -> dict[str, Any] | None:
        allowed = {
            "name", "description", "connection_id", "system_prompt", "tools", "enabled",
        }
        sets, values = [], []
        for key, value in fields.items():
            if key not in allowed:
                continue
            if key == "tools":
                value = json.dumps(value or [])
            elif key == "enabled":
                value = 1 if value else 0
            sets.append(f"{key} = ?")
            values.append(value)
        if not sets:
            return self.get_worker(worker_id)
        sets.append("updated_at = datetime('now')")
        with self._connect() as conn:
            conn.execute(
                f"UPDATE workers SET {', '.join(sets)} WHERE id = ?",
                (*values, worker_id),
            )
        return self.get_worker(worker_id)

    def delete_worker(self, worker_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM workers WHERE id = ?", (worker_id,))

    @staticmethod
    def _worker_row(row: sqlite3.Row) -> dict[str, Any]:
        worker = dict(row)
        try:
            worker["tools"] = json.loads(worker["tools"] or "[]")
        except (TypeError, ValueError):
            worker["tools"] = []
        worker["enabled"] = bool(worker["enabled"])
        return worker

    # -- capabilities ---------------------------------------------------

    def capability_enabled(self, identifier: str) -> bool:
        """Whether the owner has this Capability switched on.

        Absent means enabled. A Capability discovered for the first time --
        because AWORG shipped a new one, or the owner installed it -- should
        work without the owner having to go and turn it on, and only ever
        appears here once they have actually decided something about it.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT enabled FROM capability_state WHERE id = ?", (identifier,)
            ).fetchone()
        return True if row is None else bool(row["enabled"])

    def set_capability_enabled(self, identifier: str, enabled: bool) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO capability_state (id, enabled, updated_at) "
                "VALUES (?, ?, datetime('now')) "
                "ON CONFLICT(id) DO UPDATE SET "
                "enabled = excluded.enabled, updated_at = excluded.updated_at",
                (identifier, int(bool(enabled))),
            )

