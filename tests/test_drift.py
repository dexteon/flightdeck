"""Schema drift must degrade, never raise.

This is not hypothetical. On this machine today the board `nrt-unify` carries a
`tasks.task_source` column that the other thirteen boards do not, so the column set
genuinely differs board to board. A `SELECT *` into a strict model would already be
broken.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from flightdeck.hermes.readdb import BoardReader, BoardUnavailable
from flightdeck.hermes.queries import tasks as q

BASE_COLUMNS = """
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    body TEXT,
    assignee TEXT,
    status TEXT NOT NULL,
    priority INTEGER DEFAULT 0,
    created_at INTEGER NOT NULL,
    started_at INTEGER,
    last_heartbeat_at INTEGER,
    block_kind TEXT
"""


def _make_board(path: Path, extra: str = "", missing: tuple[str, ...] = ()) -> Path:
    columns = [c.strip() for c in BASE_COLUMNS.strip().split(",\n")]
    kept = [c for c in columns if not any(c.startswith(m + " ") for m in missing)]
    if extra:
        kept.append(extra)
    conn = sqlite3.connect(path)
    conn.execute(f"CREATE TABLE tasks ({', '.join(kept)})")
    conn.execute("CREATE TABLE task_events (id INTEGER PRIMARY KEY, task_id TEXT, kind TEXT, created_at INTEGER)")
    conn.execute(
        "INSERT INTO tasks (id, title, status, priority, created_at) VALUES ('t_1', 'one', 'ready', 3, 1000)"
    )
    conn.commit()
    conn.close()
    return path


def test_extra_column_is_ignored(tmp_path: Path) -> None:
    # The nrt-unify shape: an upstream column we know nothing about.
    db = _make_board(tmp_path / "extra.db", extra="task_source TEXT")
    reader = BoardReader("extra", db)

    assert "task_source" in reader.schema().present("tasks")
    rows = q.list_tasks(reader)

    assert len(rows) == 1
    assert rows[0]["id"] == "t_1"
    assert "task_source" not in rows[0]
    reader.close()


def test_missing_columns_come_back_as_none(tmp_path: Path) -> None:
    # An older board that predates several migrations.
    db = _make_board(tmp_path / "old.db", missing=("block_kind", "last_heartbeat_at"))
    reader = BoardReader("old", db)

    rows = q.list_tasks(reader)

    assert len(rows) == 1
    # Every requested key is present in the dict, absent ones as None.
    assert set(rows[0]) == set(q.TASK_COLUMNS)
    assert rows[0]["block_kind"] is None
    assert rows[0]["last_heartbeat_at"] is None
    assert rows[0]["title"] == "one"
    reader.close()


def test_fingerprint_changes_when_the_schema_does(tmp_path: Path) -> None:
    plain = BoardReader("plain", _make_board(tmp_path / "a.db"))
    drifted = BoardReader("drifted", _make_board(tmp_path / "b.db", extra="task_source TEXT"))

    assert plain.schema().fingerprint != drifted.schema().fingerprint

    plain.close()
    drifted.close()


def test_stale_running_tolerates_a_board_without_heartbeats(tmp_path: Path) -> None:
    db = _make_board(tmp_path / "nohb.db", missing=("last_heartbeat_at",))
    reader = BoardReader("nohb", db)

    # The query names last_heartbeat_at in its WHERE clause, so a board lacking the
    # column must surface as unavailable rather than crashing the fleet view.
    with pytest.raises(BoardUnavailable):
        q.stale_running(reader, 120)
    reader.close()


class TestUnreadableBoards:
    def test_zero_byte_file(self, tmp_path: Path) -> None:
        # The shape of C:\Users\user\.hermes\kanban.db, which is not a live database.
        db = tmp_path / "empty.db"
        db.touch()
        reader = BoardReader("empty", db)

        assert not reader.schema().has_table("tasks")
        reader.close()

    def test_truncated_file(self, tmp_path: Path) -> None:
        db = _make_board(tmp_path / "trunc.db")
        data = db.read_bytes()
        db.write_bytes(data[: len(data) // 3])
        reader = BoardReader("trunc", db)

        with pytest.raises(BoardUnavailable):
            reader.schema()
        reader.close()

    def test_missing_file(self, tmp_path: Path) -> None:
        reader = BoardReader("gone", tmp_path / "nope.db")

        with pytest.raises(BoardUnavailable):
            reader.schema()
        reader.close()

    def test_database_without_a_tasks_table(self, tmp_path: Path) -> None:
        db = tmp_path / "other.db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE something_else (id INTEGER)")
        conn.commit()
        conn.close()
        reader = BoardReader("other", db)

        assert not reader.schema().has_table("tasks")
        reader.close()


def test_reader_cannot_write(tmp_path: Path) -> None:
    db = _make_board(tmp_path / "ro.db")
    reader = BoardReader("ro", db)

    with pytest.raises(BoardUnavailable):
        reader.execute("UPDATE tasks SET title = 'nope' WHERE id = 't_1'")

    # And the row is untouched.
    assert q.get_task(reader, "t_1")["title"] == "one"
    reader.close()
