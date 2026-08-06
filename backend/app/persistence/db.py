"""SQLite connection management (Deliverable 7 SS4).

This module owns the only SQLite connection in the process. Repositories take a
connection from here; nothing else calls sqlite3.connect. A single owner is what
makes the graceful-shutdown guarantee (FR-7.5) enforceable rather than aspirational.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime

from app.config.settings import get_settings
from app.persistence.tables import DDL, SCHEMA_VERSION

_conn: sqlite3.Connection | None = None
_lock = threading.RLock()


def _configure(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    # WAL lets the dashboard read while a batch evaluation writes.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    # NORMAL is durable enough under WAL and materially faster than FULL for the
    # synchronous per-span writes in llm/client.py.
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")


def init_db() -> sqlite3.Connection:
    """Open the connection and apply the schema. Idempotent."""
    global _conn
    with _lock:
        if _conn is not None:
            return _conn

        settings = get_settings()
        settings.data_dir.mkdir(parents=True, exist_ok=True)

        # check_same_thread=False: FastAPI runs handlers across a threadpool.
        # Safety comes from _lock plus WAL, not from thread affinity.
        conn = sqlite3.connect(settings.sqlite_path, check_same_thread=False)
        _configure(conn)

        for statement in DDL:
            conn.execute(statement)
        conn.execute(
            "INSERT OR IGNORE INTO schema_meta (version, applied_at) VALUES (?, ?)",
            (SCHEMA_VERSION, datetime.now(UTC).isoformat()),
        )
        conn.commit()

        _conn = conn
        return _conn


def get_db() -> sqlite3.Connection:
    """Return the live connection, opening it on first use."""
    if _conn is None:
        return init_db()
    return _conn


def execute(sql: str, params: tuple = ()) -> sqlite3.Cursor:
    """Write helper. Serialised so concurrent nodes cannot interleave writes."""
    conn = get_db()
    with _lock:
        cursor = conn.execute(sql, params)
        conn.commit()
        return cursor


def query(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    """Read helper. WAL permits this concurrently with writers."""
    return get_db().execute(sql, params).fetchall()


def query_one(sql: str, params: tuple = ()) -> sqlite3.Row | None:
    return get_db().execute(sql, params).fetchone()


def close_db() -> None:
    """Commit, checkpoint the WAL, and close (FR-7.5).

    Called from the FastAPI lifespan shutdown handler. Truncating the WAL on the
    way out is what prevents the partially-applied state that an abrupt kill
    would otherwise leave behind.
    """
    global _conn
    with _lock:
        if _conn is None:
            return
        try:
            _conn.commit()
            _conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            _conn.close()
            _conn = None
