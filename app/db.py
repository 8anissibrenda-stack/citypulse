"""SQLite database helpers for CityPulse.

Every connection enables foreign keys and WAL journal mode.
The pipeline thread must use its own connection obtained via get_conn().
"""

import sqlite3
import threading
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_local = threading.local()


def get_conn() -> sqlite3.Connection:
    """Return a thread-local SQLite connection with best-practice PRAGMAs."""
    conn: sqlite3.Connection | None = getattr(_local, "conn", None)
    if conn is None:
        db_path = Path(settings.db_path)
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        _local.conn = conn
        logger.debug("Opened new SQLite connection for thread %s", threading.current_thread().name)
    return conn


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    """Convert a sqlite3.Row to a plain dict, or return None."""
    if row is None:
        return None
    return dict(row)


def query_all(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    """Execute a SELECT and return all rows as dicts."""
    conn = get_conn()
    cursor = conn.execute(sql, params)
    return [dict(r) for r in cursor.fetchall()]


def query_one(sql: str, params: tuple = ()) -> dict[str, Any] | None:
    """Execute a SELECT and return the first row as a dict, or None."""
    conn = get_conn()
    cursor = conn.execute(sql, params)
    return _row_to_dict(cursor.fetchone())


def execute(sql: str, params: tuple = ()) -> int:
    """Execute an INSERT/UPDATE/DELETE and return lastrowid."""
    conn = get_conn()
    cursor = conn.execute(sql, params)
    conn.commit()
    return cursor.lastrowid  # type: ignore[return-value]


def execute_many(sql: str, params_list: list[tuple]) -> None:
    """Execute a statement with many parameter sets."""
    conn = get_conn()
    conn.executemany(sql, params_list)
    conn.commit()


@contextmanager
def transaction():
    """Context manager for explicit transactions."""
    conn = get_conn()
    conn.execute("BEGIN")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def close_conn() -> None:
    """Close the thread-local connection if it exists."""
    conn: sqlite3.Connection | None = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None
        logger.debug("Closed SQLite connection for thread %s", threading.current_thread().name)
