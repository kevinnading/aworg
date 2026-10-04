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

# The only thing storage asks of another module: what a colour scheme
# is called when nobody has chosen one, and which old names have moved.
# theme.py depends on nothing, so this cannot become a cycle.
from .theme import DEFAULT_PRESET, RENAMED_PRESETS
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
    -- Tokens per minute this connection may spend. NULL or 0 means no
    -- limit, which is right for a local model. A hosted one is sold by the
    -- minute as well as by the token, and crossing the line gets the request
    -- refused mid-turn; see aworg/ratelimit.py.
    tokens_per_minute INTEGER,
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
    preset     TEXT NOT NULL DEFAULT 'aworg-light',
    overrides  TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- What the Resident is building, by name.
--
-- One row, like appearance and layout, because an Aworg has one Living
-- Workspace and therefore one project in it. The default is honest: an
-- unnamed project is what this is until the Resident learns enough about
-- the job to call it something, and "Unnamed Project" says so rather than
-- inventing a title nobody chose.
--
-- The Resident owns both fields -- there is no settings form for them. It
-- names the thing it is building the way it writes its own plan, which is
-- the arrangement the rest of this product runs on.
CREATE TABLE IF NOT EXISTS project (
    id         INTEGER PRIMARY KEY CHECK (id = 1),
    name       TEXT NOT NULL DEFAULT 'Unnamed Project',
    version    TEXT NOT NULL DEFAULT '1.0',
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
    -- What the model thought before it answered, when it says so. Kept and
    -- shown; never sent back. Reasoning is deliberately not replayed to a
    -- model -- see the note on `_input` in models/openai_responses.py -- so
    -- this is the one column here that the wire never sees, which is
    -- exactly why it is a column rather than another kind of block.
    --
    -- Before this it was streamed to the browser and then gone: an owner
    -- who reloaded lost the reasoning behind everything the Resident had
    -- just done, and could never ask why afterwards.
    thinking        TEXT,
    -- How long that reasoning took, in seconds. The interface shows it
    -- live and would otherwise have to say something vaguer afterwards
    -- about the same block of text.
    thinking_for    REAL,
    model_label     TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);

CREATE TABLE IF NOT EXISTS tasks (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    -- Everything the Resident will need to do this later, when the
    -- conversation that produced it is long out of the window. A task whose
    -- detail says "as discussed" is a task that cannot be picked up.
    detail      TEXT NOT NULL DEFAULT '',
    state       TEXT NOT NULL DEFAULT 'pending',
    -- Subtasks. A plan is a shallow tree, not a list: "build the invoice
    -- module" has parts, and the parts are what get worked.
    parent_id   TEXT,
    -- Explicit rather than by id, because the Resident reorders a plan far
    -- more often than it creates one, and insertion order is not priority.
    position    INTEGER NOT NULL DEFAULT 0,
    -- What happened. Set when a task finishes or gets stuck, so that the
    -- next reader learns something the title does not say.
    note        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_tasks_state ON tasks (state, position, id);

-- Premade workers are gone: the Resident spawns its own. An Aworg that
-- still has the old table loses it.
DROP TABLE IF EXISTS workers;

CREATE TABLE IF NOT EXISTS skill_state (
    id         TEXT PRIMARY KEY,
    enabled    INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS capability_state (
    id         TEXT PRIMARY KEY,
    enabled    INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation
    ON messages (conversation_id, id);

-- The Living Log: what happened, and mattered.
--
-- On disk rather than in memory, which is the whole difference between this
-- and Activities. An owner coming back in the morning to find out what
-- happened overnight is the case this table exists for, and runtime state
-- answers that question with silence.
CREATE TABLE IF NOT EXISTS journal (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    -- note, concern or alarm. Separate levels rather than one "bad" flag,
    -- because the autonomous loop will need to tell "something failed and
    -- was handled" from "something is wrong now"; see aworg/journal.py.
    level       TEXT NOT NULL DEFAULT 'note',
    -- What sort of thing this was: tool, worker, process, task, capability,
    -- skill, aworg. The interface groups on it; nothing branches on it.
    kind        TEXT NOT NULL DEFAULT 'aworg',
    -- Who is reporting: the Resident, a worker, a running program, or AWORG
    -- itself for the things the owner did.
    source      TEXT NOT NULL DEFAULT 'aworg',
    summary     TEXT NOT NULL,
    detail      TEXT NOT NULL DEFAULT '',
    -- The evidence, when there is any. Activities are runtime state and are
    -- forgotten in time, so this is a link that may go dead -- which is why
    -- the entry has to stand on its own without it.
    activity_id TEXT,
    at          TEXT NOT NULL DEFAULT (datetime('now')),
    -- Whether anything still needs doing about this.
    --
    -- Only concerns and alarms are ever open; a note is a record of
    -- something that happened and there is nothing to resolve about it.
    -- That is why this is not defaulted per level here -- see
    -- list_journal, which decides what "open" means in one place.
    resolved    INTEGER NOT NULL DEFAULT 0,
    resolved_at TEXT,
    -- Who closed it, and what they did. "The Resident restarted it" and
    -- "the owner said never mind" are different outcomes, and a loop that
    -- cannot tell them apart learns the wrong lesson from its own history.
    resolved_by TEXT,
    resolution  TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_journal_at ON journal (id DESC);

"""


#: Previous shipped defaults. A stored prompt matching one of these exactly
#: was written by AWORG and never touched by the owner, so it is safe to
#: bring up to date. Anything else is the owner's and is left alone -- the
#: standing instructions are theirs, and silently rewriting them would be
#: the worst kind of helpfulness.
PREVIOUS_DEFAULT_PROMPTS = ["""You are the Resident of this Aworg: a persistent
inhabitant of this machine, not an assistant that appears and forgets. You
will still be here tomorrow, holding this same conversation.

Act rather than guess. Read the file, run the command, look at what came
back. Guessing and checking cost you the same one step, and only one of them
is true.

Skills are procedures for particular kinds of work, listed below with what
each is for. Some are given to you in full; for the rest you get only the
description, and you load one by calling read_skill with its name. Do that
when a job matches a description, before you plan or write anything -- a
skill is how this machine does that job, which is not always how you would.

Plan anything past about three steps: add_tasks before you start, update_task
as you go. Old messages stop being sent to you; your plan does not.

Delegate self-contained work to a worker. It gets a fresh context of its own,
which is room you do not have to spend.

A long file will not fit in one tool call and gets cut off part way. Write it
in appended pieces, or delegate it.

Anything described as current, latest or recent is to be fetched, not
recalled. Your training stopped and you cannot tell when.

The owner cannot check your work -- that is why you are here. Never call
something done that you have not watched succeed, and when something fails,
say plainly that it failed and what it said. Speak plainly throughout: the
owner may not be a programmer and should never need to be.""", """You are the Resident of this Aworg.

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
never need to be one to work with you.""", 'You are the Resident of this Aworg.\n\nYou are not a chat assistant that appears when summoned and forgets afterward.\nYou are a persistent inhabitant of this machine. You live here. The owner you\nare speaking with installed you, and you will still be here tomorrow, holding\nthe same conversation and remembering what was decided in it.\n\nYou have tools, and you can act on this machine rather than only describe it.\nUse them instead of reasoning about what is probably there: read the file, run\nthe command, look at what came back. Guessing and checking cost you the same\none step, and only one of them is true.\n\nThe owner cannot check your work for you. That is the whole reason you are\nhere, so it matters more than anything else you do: never call something done\nthat you have not watched succeed, and when a step fails, say plainly that it\nfailed and what it said. Be clear about the difference between what you have\nverified and what you believe. Things going wrong is ordinary -- investigate\nand try again, and involve the owner when you are genuinely stuck rather than\nmerely inconvenienced.\n\nSpeak plainly and directly. The owner may not be a programmer, and should\nnever need to be one to work with you.', """You are the Resident of this Aworg.

You are not a chat assistant that appears when summoned and forgets afterward.
You are a persistent inhabitant of this machine. You live here. The owner you
are speaking with installed you, and you will still be here tomorrow, holding
the same conversation and remembering what was decided in it.

You have tools, and you can act on this machine rather than only describe it.
Use them instead of reasoning about what is probably there: read the file, run
the command, look at what came back. Guessing and checking cost you the same
one step, and only one of them is true.

For anything with more than about three steps, write the plan down with
add_tasks before you start. Your conversation is bounded and old messages stop
being sent to you; your plan is not, and it is how you know what you were
doing after they are gone. Mark one active as you begin it and done once you
have watched it succeed.

Hand work to a worker when the job is well described and self-contained,
especially writing files and checking whether something works. A worker gets a
fresh context of its own, which is room you do not have to spend.

Your replies have a size limit. A long file will not fit in one tool call --
it gets cut off part way and fails. Write it in several appended pieces, or
delegate it.

The owner cannot check your work for you. That is the whole reason you are
here, so it matters more than anything else you do: never call something done
that you have not watched succeed, and when a step fails, say plainly that it
failed and what it said. Be clear about the difference between what you have
verified and what you believe. Things going wrong is ordinary -- investigate
and try again, and involve the owner when you are genuinely stuck rather than
merely inconvenienced.

Speak plainly and directly. The owner may not be a programmer, and should
never need to be one to work with you.""", """You are the Resident of this Aworg.

You are not a chat assistant that appears when summoned and forgets afterward.
You are a persistent inhabitant of this machine. You live here. The owner you
are speaking with installed you, and you will still be here tomorrow, holding
the same conversation and remembering what was decided in it.

You have tools, and you can act on this machine rather than only describe it.
Use them instead of reasoning about what is probably there: read the file, run
the command, look at what came back. Guessing and checking cost you the same
one step, and only one of them is true.

For anything with more than about three steps, write the plan down with
add_tasks before you start. Your conversation is bounded and old messages stop
being sent to you; your plan is not, and it is how you know what you were
doing after they are gone. Mark one active as you begin it and done once you
have watched it succeed.

Hand work to a worker when the job is well described and self-contained,
especially writing files and checking whether something works. A worker gets a
fresh context of its own, which is room you do not have to spend.

Your replies have a size limit. A long file will not fit in one tool call --
it gets cut off part way and fails. Write it in several appended pieces, or
delegate it.

When something depends on what is true now rather than what you remember,
fetch it. Your training stopped at some point and you cannot tell from the
inside how long ago that was, so anything described as current, latest or
recent is a thing to look up rather than recall. Writing down remembered
facts as though they were checked is the same failure as reporting work you
did not watch succeed.

The owner cannot check your work for you. That is the whole reason you are
here, so it matters more than anything else you do: never call something done
that you have not watched succeed, and when a step fails, say plainly that it
failed and what it said. Be clear about the difference between what you have
verified and what you believe. Things going wrong is ordinary -- investigate
and try again, and involve the owner when you are genuinely stuck rather than
merely inconvenienced.

Speak plainly and directly. The owner may not be a programmer, and should
never need to be one to work with you.""", """You are the Resident of this Aworg.

You are not a chat assistant that appears when summoned and forgets afterward.
You are a persistent inhabitant of this machine. You live here. The owner you
are speaking with installed you, and you will still be here tomorrow, holding
the same conversation and remembering what was decided in it.

You have tools, and you can act on this machine rather than only describe it.
Use them instead of reasoning about what is probably there: read the file, run
the command, look at what came back. Guessing and checking cost you the same
one step, and only one of them is true.

Some kinds of work have a skill written for them -- how this machine does
that job, which is not always how you would. They are listed below with what
each is for. When one matches what you have been asked, read it with
read_skill before you plan or write anything, not afterwards.

For anything with more than about three steps, write the plan down with
add_tasks before you start. Your conversation is bounded and old messages stop
being sent to you; your plan is not, and it is how you know what you were
doing after they are gone. Mark one active as you begin it and done once you
have watched it succeed.

Hand work to a worker when the job is well described and self-contained,
especially writing files and checking whether something works. A worker gets a
fresh context of its own, which is room you do not have to spend.

Your replies have a size limit. A long file will not fit in one tool call --
it gets cut off part way and fails. Write it in several appended pieces, or
delegate it.

When something depends on what is true now rather than what you remember,
fetch it. Your training stopped at some point and you cannot tell from the
inside how long ago that was, so anything described as current, latest or
recent is a thing to look up rather than recall. Writing down remembered
facts as though they were checked is the same failure as reporting work you
did not watch succeed.

The owner cannot check your work for you. That is the whole reason you are
here, so it matters more than anything else you do: never call something done
that you have not watched succeed, and when a step fails, say plainly that it
failed and what it said. Be clear about the difference between what you have
verified and what you believe. Things going wrong is ordinary -- investigate
and try again, and involve the owner when you are genuinely stuck rather than
merely inconvenienced.

Speak plainly and directly. The owner may not be a programmer, and should
never need to be one to work with you.""", """You are the Resident of this Aworg: a persistent
inhabitant of this machine, not an assistant that appears and forgets. You
will still be here tomorrow, holding this same conversation.

Act rather than guess. Read the file, run the command, look at what came
back. Guessing and checking cost you the same one step, and only one of them
is true.

Skills are procedures for particular kinds of work, listed below with what
each is for. Some are given to you in full; for the rest you get only the
description, and you load one by calling read_skill with its name. Do that
when a job matches a description, before you plan or write anything -- a
skill is how this machine does that job, which is not always how you would.

Plan anything past about three steps: add_tasks before you start, update_task
as you go. Old messages stop being sent to you; your plan does not.

Hand the doing to a worker. Understanding what the owner wants, deciding how
it should be done, keeping the plan and saying what happened are yours; the
carrying out is theirs. Each worker gets a fresh context of its own, which is
room you do not have to spend, and several can work while you think. Do a
thing yourself when describing it would take longer than doing it.

Anything described as current, latest or recent is to be fetched, not
recalled. Your training stopped and you cannot tell when.

The owner cannot check your work -- that is why you are here. Never call
something done that you have not watched succeed, and when something fails,
say plainly that it failed and what it said. Speak plainly throughout: the
owner may not be a programmer and should never need to be.""",
"""You are the Resident of this Aworg: a persistent
inhabitant of this machine, not an assistant that appears and forgets. You
will still be here tomorrow, holding this same conversation.

Act rather than guess. Read the file, run the command, look at what came
back. Guessing and checking cost you the same one step, and only one of them
is true.

Skills are procedures for particular kinds of work, listed below with what
each is for. Some are given to you in full; for the rest you get only the
description, and you load one by calling read_skill with its name. Do that
when a job matches a description, before you plan or write anything -- a
skill is how this machine does that job, which is not always how you would.

Plan anything past about three steps: add_tasks before you start, update_task
as you go. Old messages stop being sent to you; your plan does not.

Hand the doing to a worker. Understanding what the owner wants, deciding how
it should be done, keeping the plan and saying what happened are yours; the
carrying out is theirs. Each worker gets a fresh context of its own, which is
room you do not have to spend, and several can work while you think. Do a
thing yourself when describing it would take longer than doing it.

Anything described as current, latest or recent is to be fetched, not
recalled. Your training stopped and you cannot tell when.

Anything you start is handed the Living Log's address in its environment. A
program you wrote should report its own trouble there, so a failure nobody
was watching is still found.

The owner cannot check your work -- that is why you are here. Never call
something done that you have not watched succeed, and when something fails,
say plainly that it failed and what it said. Speak plainly throughout: the
owner may not be a programmer and should never need to be."""]


#: Empty. The persona is the system prompt; this is the owner's addition
#: to it, read straight after, and AWORG has nothing to add on their behalf.
DEFAULT_SYSTEM_PROMPT = ""


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
        # Which persona the Resident is wearing. On the resident row rather
        # than in a table of its own because there is exactly one Resident
        # and it wears exactly one at a time -- and because putting it here
        # is what makes it survive everything a reset does to the rest.
        ("resident", "persona", "TEXT"),
        ("journal", "resolved", "INTEGER NOT NULL DEFAULT 0"),
        ("journal", "resolved_at", "TEXT"),
        ("journal", "resolved_by", "TEXT"),
        ("journal", "resolution", "TEXT NOT NULL DEFAULT ''"),
        ("connections", "tokens_per_minute", "INTEGER"),
        # Whether the watcher may wake the Resident when an application
        # reports trouble into a quiet Aworg. On by default: an Aworg that
        # notices and says nothing is the thing the Living Log was built to
        # stop being. Off is a real choice, though -- every waking is a
        # model call the owner did not ask for and does pay for.
        ("resident", "wake_on_trouble", "INTEGER NOT NULL DEFAULT 1"),
        # A reply written before this column existed has no reasoning stored
        # and never will -- it was streamed and lost. NULL says so honestly;
        # an empty string would claim the model thought nothing.
        ("messages", "thinking", "TEXT"),
        ("messages", "thinking_for", "REAL"),
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
                "INSERT INTO project (id) VALUES (1) ON CONFLICT(id) DO NOTHING"
            )
            conn.execute(
                "INSERT INTO layout (id) VALUES (1) ON CONFLICT(id) DO NOTHING"
            )
            self._rename_presets(conn)
            self._refresh_default_prompt(conn)

    @staticmethod
    def _rename_presets(conn) -> None:
        """Move an Aworg off a colour scheme that has been renamed or retired.

        Done here rather than on read, so that the stored value and the
        scheme actually in force are never two different answers -- which is
        what would leave the picker showing nothing selected while the
        interface was plainly wearing something.
        """
        for old_name, new_name in RENAMED_PRESETS.items():
            conn.execute(
                "UPDATE appearance SET preset = ? WHERE id = 1 AND preset = ?",
                (new_name, old_name),
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
        tokens_per_minute: int | None = None,
    ) -> dict[str, Any]:
        connection_id = uuid.uuid4().hex[:12]
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO connections (id, name, provider, model, base_url, "
                "tags, reasoning, context, tokens_per_minute, enabled) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    connection_id,
                    name,
                    provider,
                    model,
                    base_url or None,
                    json.dumps(tags or []),
                    reasoning,
                    context,
                    tokens_per_minute or None,
                    1 if enabled else 0,
                ),
            )
        return self.get_connection(connection_id)  # type: ignore[return-value]

    def update_connection(self, connection_id: str, **fields: Any) -> dict[str, Any] | None:
        allowed = {
            "name", "provider", "model", "base_url", "tags", "reasoning",
            "context", "tokens_per_minute", "enabled",
        }
        sets, values = [], []
        for key, value in fields.items():
            if key not in allowed:
                continue
            # None means "not supplied" for every field except the context
            # ceiling, where it is a real value: unknown. Callers clear it
            # by passing 0, which is not a size any model has.
            if key in ("context", "tokens_per_minute"):
                # None means "not supplied" for every field except these two
                # ceilings, where it is a real value: unknown, and no limit.
                # Callers clear them by passing 0, which is neither a window
                # size nor an allowance any provider has.
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
            # Absent on a database that predates the column, which reads as
            # "nobody has said" rather than as an error.
            "tokens_per_minute": (
                row["tokens_per_minute"] if "tokens_per_minute" in row.keys() else None
            ),
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
            # Absent on a database that predates personas, which reads as
            # no persona rather than as an error.
            "persona": (row["persona"] if "persona" in row.keys() else None),
            # Same treatment, and the default is the same as the column's:
            # a database from before the watcher could wake anybody is one
            # whose owner has never said no.
            "wake_on_trouble": bool(
                row["wake_on_trouble"] if "wake_on_trouble" in row.keys() else 1
            ),
        }

    def update_resident(self, **fields: Any) -> dict[str, Any]:
        allowed = {
            "primary_connection_id",
            "worker_connection_id",
            "system_prompt",
            "current_conversation_id",
            "persona",
            "wake_on_trouble",
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

    #: How much of a name and a version to keep. Both are written by a model
    #: and both are rendered into a pane header that has one line to give
    #: them, so the bound is the interface's rather than the database's.
    MAX_PROJECT_NAME = 60
    MAX_PROJECT_VERSION = 16

    def get_project(self) -> dict[str, Any]:
        """What the Resident is building, by name."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM project WHERE id = 1").fetchone()
        if row is None:
            return {"name": "Unnamed Project", "version": "1.0"}
        return {"name": row["name"], "version": row["version"]}

    def set_project(
        self, name: str | None = None, version: str | None = None
    ) -> dict[str, Any]:
        """Rename it, re-version it, or both.

        Either may be omitted, and omitting one leaves it alone -- a Resident
        that has decided what the thing is called should not have to restate
        its version to say so, and a version bump should not be a chance to
        lose the name.

        Blank is the same as omitted rather than the same as empty. A header
        reading "Project: v1.0" would be a worse answer than the name it
        already had, and a model that sends an empty string usually means it
        had nothing to add.
        """
        fields: list[str] = []
        values: list[Any] = []
        if name is not None and name.strip():
            fields.append("name = ?")
            values.append(name.strip()[: self.MAX_PROJECT_NAME])
        if version is not None and version.strip():
            fields.append("version = ?")
            values.append(version.strip()[: self.MAX_PROJECT_VERSION])
        if not fields:
            return self.get_project()
        with self._connect() as conn:
            conn.execute(
                f"UPDATE project SET {', '.join(fields)}, "
                "updated_at = datetime('now') WHERE id = 1",
                values,
            )
        return self.get_project()

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
        thinking: str | None = None,
        thinking_for: float | None = None,
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
        # Empty is stored as nothing. "The model thought and said none of it"
        # and "there is no reasoning here" are the same fact, and NULL is the
        # one that does not put an empty box in the conversation.
        thought = (thinking or "").strip() or None
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO messages "
                "(conversation_id, role, content, blocks, thinking, thinking_for, "
                "model_label) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (conversation_id, role, content, payload, thought,
                 thinking_for if thought else None, model_label),
            )
            return int(cursor.lastrowid)

    def messages(self, conversation_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                # The id comes back because summarising has to record how
                # far it has read; nothing else uses it, and it is harmless
                # to the callers that ignore it.
                "SELECT id, role, content, blocks, thinking, thinking_for, "
                "model_label, created_at "
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

    #: What a reset can put back, and what each part is called where the
    #: owner chooses it.
    #:
    #: A list rather than one verb because "reset" turned out to mean several
    #: different things an owner might want separately: a fresh conversation
    #: is a different request from a fresh machine, and neither should cost
    #: them their model connections. Each part stands alone -- none of them
    #: depends on another having been chosen.
    RESET_PARTS = {
        "conversation": "Conversation and messages",
        "tasks": "Tasks in the plan",
        "journal": "The Living Log",
        "workspace": "Files in the Living Workspace",
        "trash": "The trash",
        "processes": "Running programs (servers and the like)",
        "capabilities": "Capabilities, back to the ones that shipped",
        "skills": "Skills, back to the ones that shipped",
        "project": "The project's name and version",
        "layout": "Pane sizes",
        "appearance": "Colour scheme",
        "persona": "Personas, and the one being worn",
        "prompt": "What you added to the Persona",
        "connections": "Model connections and their credentials",
    }

    #: Chosen for them when the dialog opens. The four left out are the ones
    #: an owner sets up once and would not expect a reset to take: what the
    #: Resident is connected to, what it looks like, who it is, and the
    #: instructions they wrote it. Every part is still available; these
    #: simply are not assumed.
    RESET_DEFAULTS = tuple(
        part for part in RESET_PARTS
        if part not in ("connections", "appearance", "persona", "prompt")
    )

    #: Tables emptied wholesale, by the part that owns them.
    _RESET_TABLES = {
        "conversation": ("messages", "conversations"),
        "tasks": ("tasks",),
        "journal": ("journal",),
        "capabilities": ("capability_state",),
        "skills": ("skill_state",),
        "connections": ("connections",),
    }

    def count_capability_state(self) -> int:
        """How many capability switches the owner has moved."""
        with self._connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) c FROM capability_state"
            ).fetchone()["c"]

    def count_skill_state(self) -> int:
        """How many skill switches the owner has moved."""
        with self._connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) c FROM skill_state"
            ).fetchone()["c"]

    def factory_reset(self, parts: Any = None) -> dict[str, int]:
        """Put the chosen parts back the way a fresh Aworg has them.

        Deliberately explicit about every table rather than dropping the file
        and rebuilding. A reset that recreates the schema from scratch is a
        reset that silently discards any migration an owner's database has
        been through, and the failure would only show on the next upgrade.

        `parts` is a set of RESET_PARTS keys; None means all of them, which
        is what a factory reset has always meant. Counts come back per part
        rather than per table, because the part is what the owner chose.
        """
        chosen = set(self.RESET_PARTS if parts is None else parts)
        removed: dict[str, int] = {}
        with self._connect() as conn:
            for part, tables in self._RESET_TABLES.items():
                if part not in chosen:
                    continue
                count = 0
                for table in tables:
                    count += conn.execute(
                        f"SELECT COUNT(*) c FROM {table}"
                    ).fetchone()["c"]
                    conn.execute(f"DELETE FROM {table}")
                removed[part] = count

            if "conversation" in chosen:
                # The pointer goes with the messages it points at; a
                # conversation id surviving its conversation is a Resident
                # writing into a row that is no longer there.
                conn.execute(
                    "UPDATE resident SET current_conversation_id = NULL WHERE id = 1"
                )
            if "connections" in chosen:
                conn.execute(
                    "UPDATE resident SET primary_connection_id = NULL,"
                    " worker_connection_id = NULL WHERE id = 1"
                )
            if "prompt" in chosen:
                # An owner who edited theirs and asked for it back gets the
                # shipped one; anyone who did not choose this keeps what they
                # wrote, which is the whole point of it being separate.
                conn.execute(
                    "UPDATE resident SET system_prompt = ? WHERE id = 1",
                    (DEFAULT_SYSTEM_PROMPT,),
                )
            if "persona" in chosen:
                conn.execute("UPDATE resident SET persona = NULL WHERE id = 1")
            if "project" in chosen:
                # The name survived a reset once, and the Resident -- asked
                # for something new -- read that it was working on "Signal
                # Garden" and dutifully built Signal Garden v2.0. It was not
                # remembering; it was told, by a row nothing had cleared.
                conn.execute(
                    "UPDATE project SET name = 'Unnamed Project', version = '1.0',"
                    " updated_at = datetime('now') WHERE id = 1"
                )
            if "layout" in chosen:
                conn.execute("UPDATE layout SET sizes = '{}' WHERE id = 1")
            if "appearance" in chosen:
                conn.execute(
                    "UPDATE appearance SET preset = ?,"
                    " overrides = '{}' WHERE id = 1",
                    (DEFAULT_PRESET,),
                )

        # Scrub what was deleted, rather than merely unlinking it.
        #
        # DELETE takes rows out of the tables and leaves their content in the
        # file's free pages. Checked rather than assumed: after a reset that
        # emptied a conversation, a sentence from it was still findable in
        # the bytes at a fixed offset. An owner who resets an Aworg because
        # they typed something into it they regret has not been given what
        # they asked for.
        #
        # secure_delete zeroes pages as they are freed from here on; VACUUM
        # rewrites the file now, dropping every free page the deletes above
        # just made. Both are needed: the pragma is for the future, the
        # vacuum is for what has already happened. VACUUM cannot run inside a
        # transaction, hence its own connection with autocommit.
        scrub = sqlite3.connect(self.path, isolation_level=None)
        try:
            scrub.execute("PRAGMA secure_delete = ON")
            scrub.execute("VACUUM")
        finally:
            scrub.close()
        return removed

    # -- tasks ----------------------------------------------------------

    #: The states a task can be in. `blocked` is the one that earns its
    #: place: a Resident that cannot proceed should say so and move on to
    #: something else, rather than either abandoning the task or grinding at
    #: it. `abandoned` is deliberately distinct from `done` -- a plan that
    #: quietly drops what it could not manage is a plan that lies.
    TASK_STATES = ("pending", "active", "blocked", "done", "abandoned")
    OPEN_STATES = ("pending", "active", "blocked")

    def list_tasks(
        self, states: tuple[str, ...] | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM tasks"
        params: list[Any] = []
        if states:
            query += f" WHERE state IN ({','.join('?' * len(states))})"
            params.extend(states)
        # Active first so the thing being worked is never below a scroll or
        # below a truncation, then by the order the plan was given.
        query += (
            " ORDER BY CASE state WHEN 'active' THEN 0 WHEN 'blocked' THEN 1"
            " WHEN 'pending' THEN 2 ELSE 3 END, position, id"
        )
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(query, params).fetchall()]

    # -- the Living Log -------------------------------------------------

    def add_journal_entry(
        self,
        summary: str,
        level: str = "note",
        kind: str = "aworg",
        source: str = "aworg",
        detail: str = "",
        activity_id: str | None = None,
        keep: int = 500,
    ) -> dict[str, Any]:
        """Write one Living Log entry, and drop the oldest past the cap.

        Pruned here rather than on a timer, because the only moment the table
        can grow is this one and a sweep that runs on a schedule is a sweep
        that has not run yet when the owner looks.
        """
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO journal (level, kind, source, summary, detail, activity_id)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (level, kind, source, summary, detail, activity_id),
            )
            conn.execute(
                "DELETE FROM journal WHERE id <= ("
                "  SELECT id FROM journal ORDER BY id DESC LIMIT 1 OFFSET ?)",
                (keep,),
            )
            row = conn.execute(
                "SELECT * FROM journal WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return dict(row) if row else {}

    #: What counts as still open. Notes are never open -- a note records
    #: something that happened and there is nothing to do about it -- so
    #: "unresolved" is narrower than "not yet marked resolved", and the
    #: difference is defined here rather than at each call site.
    OPEN_LEVELS = ("concern", "alarm")

    def list_journal(
        self, limit: int = 100, open_only: bool = False
    ) -> list[dict[str, Any]]:
        """Newest first, because the answer to "what happened" starts at the end.

        `open_only` is what the periodic inspection asks for: the things that
        went wrong and have not been dealt with. Everything else is history,
        and a loop that re-reads history every few minutes would keep
        rediscovering problems it already fixed.
        """
        query = "SELECT * FROM journal"
        params: list[Any] = []
        if open_only:
            query += (
                f" WHERE resolved = 0 AND level IN "
                f"({','.join('?' * len(self.OPEN_LEVELS))})"
            )
            params.extend(self.OPEN_LEVELS)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(query, params).fetchall()]

    def journal_reporters(self) -> list[str]:
        """Applications that have actually used the Living Log.

        Evidence that the channel is connected rather than merely available.
        An endpoint nobody has posted to is a promise, and the Lifecycle
        stepper is built on what is observably true.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT source FROM journal WHERE kind = 'application'"
            ).fetchall()
        return [r["source"].split(":", 1)[-1] for r in rows]

    def get_journal_entry(self, entry_id: int) -> dict[str, Any] | None:
        """One entry, by id.

        So that closing an entry can be refused for a reason rather than
        applied blindly. "There is no such entry", "that one is a note and
        has nothing to resolve" and "somebody already closed that" are three
        different answers, and an UPDATE that touches no rows gives the
        caller none of them.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM journal WHERE id = ?", (entry_id,)
            ).fetchone()
        return dict(row) if row else None

    def journal_has(self, summary: str) -> bool:
        """Whether this exact line has been written before.

        For standing conditions rather than events. "Workers are running on
        the Resident's model" is true until the owner changes a setting, and
        a log that repeated it once per delegated job would bury the things
        that actually happened.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM journal WHERE summary = ? LIMIT 1", (summary,)
            ).fetchone()
        return row is not None

    def resolve_journal_entry(
        self, entry_id: int, by: str = "resident", resolution: str = ""
    ) -> dict[str, Any] | None:
        """Close one entry, saying who closed it and what they did.

        Both halves matter to whatever reads this back. "The Resident
        restarted it" and "the owner said never mind" are different outcomes,
        and a repair loop that cannot tell them apart would learn the wrong
        lesson from its own history.
        """
        with self._connect() as conn:
            conn.execute(
                "UPDATE journal SET resolved = 1, resolved_at = datetime('now'),"
                " resolved_by = ?, resolution = ? WHERE id = ?",
                (by, resolution.strip(), entry_id),
            )
            row = conn.execute(
                "SELECT * FROM journal WHERE id = ?", (entry_id,)
            ).fetchone()
        return dict(row) if row else None

    def clear_journal(self) -> int:
        with self._connect() as conn:
            count = conn.execute("SELECT COUNT(*) c FROM journal").fetchone()["c"]
            conn.execute("DELETE FROM journal")
        return count

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None

    def add_tasks(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Add several tasks at once, because a plan arrives as a plan.

        One call rather than one per task: a Resident laying out eight steps
        should not spend eight round trips doing it, and eight separate calls
        is eight chances to be interrupted half way through a plan.
        """
        created: list[str] = []
        with self._connect() as conn:
            start = conn.execute(
                "SELECT COALESCE(MAX(position), 0) p FROM tasks"
            ).fetchone()["p"]
            for offset, item in enumerate(items, 1):
                task_id = uuid.uuid4().hex[:12]
                conn.execute(
                    "INSERT INTO tasks (id, title, detail, parent_id, position) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        task_id,
                        str(item.get("title") or "").strip() or "Untitled task",
                        str(item.get("detail") or "").strip(),
                        item.get("parent_id"),
                        start + offset,
                    ),
                )
                created.append(task_id)
        return [t for t in (self.get_task(i) for i in created) if t]

    def update_task(self, task_id: str, **fields: Any) -> dict[str, Any] | None:
        allowed = {"title", "detail", "state", "parent_id", "position", "note"}
        sets, values = [], []
        for key, value in fields.items():
            if key not in allowed or value is None:
                continue
            sets.append(f"{key} = ?")
            values.append(value)
        if not sets:
            return self.get_task(task_id)
        sets.append("updated_at = datetime('now')")
        with self._connect() as conn:
            conn.execute(
                f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?", (*values, task_id)
            )
        return self.get_task(task_id)

    def delete_task(self, task_id: str) -> None:
        with self._connect() as conn:
            # Children go with the parent. A subtask whose parent is gone has
            # no meaning left, and orphans would accumulate invisibly.
            conn.execute("DELETE FROM tasks WHERE id = ? OR parent_id = ?",
                         (task_id, task_id))

    def clear_tasks(self, states: tuple[str, ...] = ("done", "abandoned")) -> int:
        """Forget finished work. Open tasks are never touched."""
        with self._connect() as conn:
            cursor = conn.execute(
                f"DELETE FROM tasks WHERE state IN ({','.join('?' * len(states))})",
                states,
            )
            return cursor.rowcount

    def task_counts(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT state, COUNT(*) n FROM tasks GROUP BY state"
            ).fetchall()
        return {row["state"]: row["n"] for row in rows}

    # -- capabilities ---------------------------------------------------

    def skill_enabled(self, name: str) -> bool:
        """Whether the owner has this skill switched on.

        Absent means enabled, exactly as for capabilities: a skill that
        appears because AWORG shipped it or the owner dropped it in should
        work without anyone going to turn it on.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT enabled FROM skill_state WHERE id = ?", (name,)
            ).fetchone()
        return True if row is None else bool(row["enabled"])

    def set_skill_enabled(self, name: str, enabled: bool) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO skill_state (id, enabled, updated_at) "
                "VALUES (?, ?, datetime('now')) "
                "ON CONFLICT(id) DO UPDATE SET "
                "enabled = excluded.enabled, updated_at = excluded.updated_at",
                (name, int(bool(enabled))),
            )

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

