"""Read-only access to Hermes board databases.

This is the correctness core. Three rules, none of them negotiable:

1. **Never write.** Connections are opened with the ``?mode=ro`` URI plus
   ``PRAGMA query_only=ON``. Hermes coordinates its workers with WAL +
   ``BEGIN IMMEDIATE`` + compare-and-swap on ``tasks.status``/``claim_lock``; a second
   writer that does not speak that protocol corrupts dispatcher state.
2. **Never read the file as raw bytes.** Closing any plain file descriptor on a SQLite
   database cancels that process's advisory locks for the whole file. Always go through
   a sqlite3 connection.
3. **Never ``SELECT *``.** Hermes applies additive column migrations on its own connect,
   so the column set drifts. Queries intersect what they want with what is present.

The connect pattern copies Hermes' own foreign-reader path at
``hermes_cli/kanban_db_connect.py:679``, and the transient-IOERR retry budget mirrors
``hermes_state.py:162-169``: a concurrent WAL checkpoint can surface ``disk I/O error``
to a read-only connection for a millisecond-wide window, because a ro connection cannot
write the ``-shm`` recovery index.
"""

from __future__ import annotations

import logging
import queue
import sqlite3
import threading
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import settings

log = logging.getLogger(__name__)

# Tables we introspect and query. Anything outside this set is not ours to read.
KNOWN_TABLES: tuple[str, ...] = (
    "tasks",
    "task_runs",
    "task_events",
    "task_links",
    "task_comments",
    "task_attachments",
)

_TRANSIENT_MARKERS = ("disk i/o error", "database is locked", "database is busy")


class BoardUnavailable(RuntimeError):
    """A board database could not be read. Carries a human-readable reason."""

    def __init__(self, slug: str, reason: str) -> None:
        super().__init__(f"{slug}: {reason}")
        self.slug = slug
        self.reason = reason


def _is_transient(exc: BaseException) -> bool:
    return any(m in str(exc).lower() for m in _TRANSIENT_MARKERS)


def _connect_ro(path: Path) -> sqlite3.Connection:
    """Open one read-only connection, exactly as Hermes opens a foreign reader."""
    uri = path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute(f"PRAGMA busy_timeout={settings.sqlite_busy_timeout_ms}")
    return conn


@dataclass(slots=True)
class _Pooled:
    conn: sqlite3.Connection
    last_used: float


@dataclass(frozen=True, slots=True)
class SchemaInfo:
    """Which columns each known table actually has, plus a drift fingerprint."""

    columns: dict[str, frozenset[str]]
    fingerprint: str

    def present(self, table: str) -> frozenset[str]:
        return self.columns.get(table, frozenset())

    def has_table(self, table: str) -> bool:
        return bool(self.columns.get(table))


def _fingerprint(columns: dict[str, frozenset[str]]) -> str:
    import hashlib

    parts = []
    for table in sorted(columns):
        cols = ",".join(sorted(columns[table]))
        parts.append(f"{table}({cols})")
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:16]


class BoardReader:
    """A pooled read-only reader for one board database."""

    def __init__(self, slug: str, path: Path) -> None:
        self.slug = slug
        self.path = path
        self._pool: queue.LifoQueue[_Pooled] = queue.LifoQueue()
        self._live = 0
        self._lock = threading.Lock()
        self._schema: SchemaInfo | None = None
        self._schema_mtime: float | None = None

    # -- connection lifecycle -------------------------------------------------

    def _acquire(self) -> sqlite3.Connection:
        cutoff = time.monotonic() - settings.pool_idle_evict_seconds
        while True:
            try:
                pooled = self._pool.get_nowait()
            except queue.Empty:
                break
            if pooled.last_used >= cutoff:
                return pooled.conn
            self._discard(pooled.conn)
        with self._lock:
            if self._live >= settings.pool_max_per_board:
                # Pool is saturated: wait for a connection rather than unbounded growth.
                pooled = self._pool.get(timeout=10.0)
                return pooled.conn
            self._live += 1
        try:
            return _connect_ro(self.path)
        except BaseException:
            with self._lock:
                self._live -= 1
            raise

    def _release(self, conn: sqlite3.Connection) -> None:
        self._pool.put(_Pooled(conn=conn, last_used=time.monotonic()))

    def _discard(self, conn: sqlite3.Connection) -> None:
        try:
            conn.close()
        except Exception:
            pass
        with self._lock:
            self._live = max(0, self._live - 1)

    def close(self) -> None:
        while True:
            try:
                self._discard(self._pool.get_nowait().conn)
            except queue.Empty:
                return

    # -- query execution ------------------------------------------------------

    def execute(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        """Run one query with the transient-IOERR retry budget.

        Blocking. Callers on the event loop must go through ``run_in_threadpool``.
        """
        attempts = max(1, settings.read_retry_attempts)
        last: BaseException | None = None
        for attempt in range(attempts):
            conn: sqlite3.Connection | None = None
            try:
                conn = self._acquire()
                rows = conn.execute(sql, tuple(params)).fetchall()
                self._release(conn)
                return rows
            except sqlite3.Error as exc:
                last = exc
                if conn is not None:
                    # A connection that just errored is suspect; do not pool it back.
                    self._discard(conn)
                if not _is_transient(exc) or attempt == attempts - 1:
                    break
                time.sleep(settings.read_retry_backoff_seconds)
        reason = f"{type(last).__name__}: {last}" if last else "unknown read failure"
        raise BoardUnavailable(self.slug, reason)

    # -- schema introspection -------------------------------------------------

    def schema(self) -> SchemaInfo:
        """Column sets per known table, cached until the file mtime changes."""
        try:
            mtime = self.path.stat().st_mtime
        except OSError as exc:
            raise BoardUnavailable(self.slug, f"stat failed: {exc}") from exc

        cached = self._schema
        if cached is not None and self._schema_mtime == mtime:
            return cached

        columns: dict[str, frozenset[str]] = {}
        for table in KNOWN_TABLES:
            rows = self.execute(f"PRAGMA table_info({table})")
            if rows:
                columns[table] = frozenset(r["name"] for r in rows)

        info = SchemaInfo(columns=columns, fingerprint=_fingerprint(columns))
        self._schema = info
        self._schema_mtime = mtime
        return info

    def select_list(self, table: str, wanted: Iterable[str]) -> list[str]:
        """The subset of ``wanted`` this database actually has, in the given order.

        Columns the database lacks are simply absent from the result; the caller fills
        them with ``None``. This is what makes an upstream schema bump a no-op for us.
        """
        present = self.schema().present(table)
        return [c for c in wanted if c in present]

    @staticmethod
    def rows_as_dicts(
        wanted: Sequence[str], rows: Iterable[sqlite3.Row]
    ) -> list[dict[str, Any]]:
        """Materialize rows with every ``wanted`` key present, missing ones as None.

        The SELECT only asked for columns this database has, so anything else in
        ``wanted`` is a column upstream dropped or has not added yet. It comes back as
        ``None`` rather than a KeyError, which is the whole drift-tolerance contract.
        """
        out: list[dict[str, Any]] = []
        for row in rows:
            keys = set(row.keys())
            out.append({c: (row[c] if c in keys else None) for c in wanted})
        return out


class ReaderCache:
    """One :class:`BoardReader` per board path, reused across requests."""

    def __init__(self) -> None:
        self._readers: dict[str, BoardReader] = {}
        self._lock = threading.Lock()

    def get(self, slug: str, path: Path) -> BoardReader:
        with self._lock:
            reader = self._readers.get(slug)
            if reader is not None and reader.path == path:
                return reader
            if reader is not None:
                reader.close()
            reader = BoardReader(slug, path)
            self._readers[slug] = reader
            return reader

    def drop(self, slug: str) -> None:
        with self._lock:
            reader = self._readers.pop(slug, None)
        if reader is not None:
            reader.close()

    def close_all(self) -> None:
        with self._lock:
            readers = list(self._readers.values())
            self._readers.clear()
        for reader in readers:
            reader.close()


readers = ReaderCache()
