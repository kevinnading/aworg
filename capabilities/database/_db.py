"""Shared by the database tools: saved connections, drivers, and opening one.

Connections are kept by name in connections.json in this folder, as URLs:

    sqlite:///C:/path/to/file.db      (or a path relative to the workspace)
    postgresql://user:password@host:5432/dbname
    mysql://user:password@host:3306/dbname

SQLite needs nothing. PostgreSQL (psycopg) and MySQL (PyMySQL) drivers are
installed into _lib/ in this folder by db_install_driver, so removing the
capability removes them. The file holds passwords in plain text: it is the
owner's machine, and there is no secret store a capability can use yet.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

from aworg.tools.base import ToolError

HERE = Path(__file__).parent
CONNECTIONS = HERE / "connections.json"
LIB = HERE / "_lib"

if LIB.is_dir() and str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

DRIVERS = {"postgresql": "psycopg[binary]", "mysql": "PyMySQL"}
KINDS = {"sqlite": "sqlite", "postgres": "postgresql", "postgresql": "postgresql", "mysql": "mysql"}


def saved() -> dict[str, str]:
    try:
        return json.loads(CONNECTIONS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(connections: dict[str, str]) -> None:
    CONNECTIONS.write_text(json.dumps(connections, indent=2), encoding="utf-8")


def kind_of(url: str) -> str:
    scheme = urlparse(url).scheme.split("+")[0].lower()
    if scheme not in KINDS:
        raise ToolError(f"Unsupported database {scheme!r}: use sqlite://, postgresql:// or mysql://.")
    return KINDS[scheme]


def hide_password(url: str) -> str:
    p = urlparse(url)
    if p.password:
        return url.replace(f":{p.password}@", ":***@", 1)
    return url


def resolve(name: str) -> str:
    connections = saved()
    if name not in connections:
        known = ", ".join(connections) or "none saved yet"
        raise ToolError(f"No connection called {name!r}. Saved: {known}. Save one with db_connect.")
    return connections[name]


def sqlite_path(url: str, workspace: Path | None) -> Path:
    """The file a sqlite URL names. After `sqlite:///`: a drive letter or a
    leading `/` is absolute; anything else is relative to the workspace."""
    if url.startswith("sqlite:////"):
        rest = "/" + url[len("sqlite:////"):]
    elif url.startswith("sqlite:///"):
        rest = url[len("sqlite:///"):]
    else:
        rest = url.split("://", 1)[1]
    path = Path(unquote(rest))
    if not path.is_absolute() and workspace is not None:
        path = workspace / path
    return path


def open_connection(url: str, workspace: Path | None, read_only: bool):
    """A DB-API connection, read-only when asked, for the URL's kind."""
    kind = kind_of(url)
    if kind == "sqlite":
        path = sqlite_path(url, workspace)
        if read_only:
            if not path.exists():
                raise ToolError(f"No SQLite file at {path}.")
            return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=10)
        return sqlite3.connect(str(path), timeout=10)

    p = urlparse(url)
    if kind == "postgresql":
        try:
            import psycopg
        except ImportError:
            raise ToolError("The PostgreSQL driver is not installed. Run db_install_driver with kind 'postgresql'.") from None
        conn = psycopg.connect(url.replace("postgres://", "postgresql://", 1), connect_timeout=10)
        if read_only:
            conn.read_only = True
        return conn

    try:
        import pymysql
    except ImportError:
        raise ToolError("The MySQL driver is not installed. Run db_install_driver with kind 'mysql'.") from None
    conn = pymysql.connect(
        host=p.hostname or "localhost", port=p.port or 3306,
        user=unquote(p.username or ""), password=unquote(p.password or ""),
        database=p.path.lstrip("/") or None, connect_timeout=10, autocommit=False,
    )
    if read_only:
        with conn.cursor() as cur:
            cur.execute("SET SESSION TRANSACTION READ ONLY")
    return conn


def table(columns: list[str], rows: list[tuple], limit: int) -> str:
    """Rows as a plain text table, cells cut at 80 characters."""
    def cell(v):
        s = "NULL" if v is None else str(v)
        s = s.replace("\n", "\\n")
        return s if len(s) <= 80 else s[:77] + "..."
    body = [[cell(v) for v in r] for r in rows[:limit]]
    widths = [max([len(c)] + [len(r[i]) for r in body]) for i, c in enumerate(columns)]
    line = lambda vals: " | ".join(v.ljust(w) for v, w in zip(vals, widths))
    out = [line(columns), "-+-".join("-" * w for w in widths)] + [line(r) for r in body]
    return "\n".join(out)
