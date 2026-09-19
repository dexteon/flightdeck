"""Event, run, and link reads.

``task_events`` is append-only with an integer primary key, which is what makes the
tailer cheap: ``WHERE id > ?`` on a covering index costs microseconds even on
`ai-fraud-guide`, which holds 16218 rows.

Volumes measured on that board: heartbeat 5516, spawned 2245, claimed 2245, promoted
1200, crashed 1099, created 1098, completed 1000, gave_up 999. Heartbeats dominate by an
order of magnitude, which is why the tailer batches a tick into one frame instead of
emitting per event.
"""

from __future__ import annotations

import json
from typing import Any

from ..readdb import BoardReader

EVENT_COLUMNS: tuple[str, ...] = ("id", "task_id", "run_id", "kind", "payload", "created_at")

RUN_COLUMNS: tuple[str, ...] = (
    "id",
    "task_id",
    "profile",
    "step_key",
    "status",
    "outcome",
    "summary",
    "error",
    "metadata",
    "worker_pid",
    "claim_lock",
    "claim_expires",
    "last_heartbeat_at",
    "max_runtime_seconds",
    "started_at",
    "ended_at",
)

#: Events that mean a run finished one way or another. Drives alerting.
TERMINAL_KINDS: frozenset[str] = frozenset(
    {"completed", "crashed", "blocked", "gave_up", "timed_out", "block_loop_detected"}
)

#: High-volume and low-information. Still tailed (they prove liveness) but never
#: worth surfacing as an activity-feed line.
NOISE_KINDS: frozenset[str] = frozenset({"heartbeat"})


def _select(reader: BoardReader, table: str, wanted: tuple[str, ...]) -> str:
    cols = reader.select_list(table, wanted)
    if not cols:
        raise ValueError(f"{table} has none of the requested columns")
    return ", ".join(f'"{c}"' for c in cols)


def _decode(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse the JSON ``payload`` column, leaving malformed values as raw text."""
    for row in rows:
        raw = row.get("payload")
        if isinstance(raw, str) and raw:
            try:
                row["payload"] = json.loads(raw)
            except json.JSONDecodeError:
                pass
    return rows


def max_event_id(reader: BoardReader) -> int:
    rows = reader.execute("SELECT MAX(id) AS top FROM task_events")
    top = rows[0]["top"] if rows else None
    return int(top or 0)


def events_since(reader: BoardReader, cursor: int, limit: int = 500) -> list[dict[str, Any]]:
    select = _select(reader, "task_events", EVENT_COLUMNS)
    rows = reader.execute(
        f"SELECT {select} FROM task_events WHERE id > ? ORDER BY id ASC LIMIT ?",
        (cursor, limit),
    )
    return _decode(BoardReader.rows_as_dicts(EVENT_COLUMNS, rows))


def events_for_task(reader: BoardReader, task_id: str, limit: int = 200) -> list[dict[str, Any]]:
    select = _select(reader, "task_events", EVENT_COLUMNS)
    rows = reader.execute(
        f"SELECT {select} FROM task_events WHERE task_id = ? "
        "ORDER BY created_at DESC, id DESC LIMIT ?",
        (task_id, limit),
    )
    return _decode(BoardReader.rows_as_dicts(EVENT_COLUMNS, rows))


def event_kind_counts(reader: BoardReader, since: int | None = None) -> dict[str, int]:
    if since is None:
        rows = reader.execute("SELECT kind, COUNT(*) AS n FROM task_events GROUP BY kind")
    else:
        rows = reader.execute(
            "SELECT kind, COUNT(*) AS n FROM task_events WHERE created_at >= ? GROUP BY kind",
            (since,),
        )
    return {row["kind"]: row["n"] for row in rows}


def runs_for_task(reader: BoardReader, task_id: str, limit: int = 50) -> list[dict[str, Any]]:
    select = _select(reader, "task_runs", RUN_COLUMNS)
    rows = reader.execute(
        f"SELECT {select} FROM task_runs WHERE task_id = ? ORDER BY started_at DESC LIMIT ?",
        (task_id, limit),
    )
    return BoardReader.rows_as_dicts(RUN_COLUMNS, rows)


def open_runs(reader: BoardReader) -> list[dict[str, Any]]:
    """Runs still marked running. The fleet's claimed work, live or wedged."""
    select = _select(reader, "task_runs", RUN_COLUMNS)
    rows = reader.execute(
        f"SELECT {select} FROM task_runs WHERE status = 'running' ORDER BY started_at ASC"
    )
    return BoardReader.rows_as_dicts(RUN_COLUMNS, rows)


def run_outcome_counts(reader: BoardReader) -> list[dict[str, Any]]:
    rows = reader.execute(
        "SELECT profile, outcome, status, COUNT(*) AS n FROM task_runs "
        "GROUP BY profile, outcome, status"
    )
    return [dict(row) for row in rows]


def links(reader: BoardReader) -> list[dict[str, str]]:
    rows = reader.execute("SELECT parent_id, child_id FROM task_links")
    return [{"parent_id": r["parent_id"], "child_id": r["child_id"]} for r in rows]


def links_for_tasks(reader: BoardReader, task_ids: list[str]) -> list[dict[str, str]]:
    if not task_ids:
        return []
    marks = ", ".join("?" for _ in task_ids)
    rows = reader.execute(
        f"SELECT parent_id, child_id FROM task_links "
        f"WHERE parent_id IN ({marks}) OR child_id IN ({marks})",
        task_ids + task_ids,
    )
    return [{"parent_id": r["parent_id"], "child_id": r["child_id"]} for r in rows]


def comments_for_task(reader: BoardReader, task_id: str) -> list[dict[str, Any]]:
    wanted = ("id", "task_id", "author", "body", "created_at")
    select = _select(reader, "task_comments", wanted)
    rows = reader.execute(
        f"SELECT {select} FROM task_comments WHERE task_id = ? ORDER BY created_at ASC",
        (task_id,),
    )
    return BoardReader.rows_as_dicts(wanted, rows)


def attachments_for_task(reader: BoardReader, task_id: str) -> list[dict[str, Any]]:
    wanted = ("id", "task_id", "filename", "content_type", "size", "uploaded_by", "created_at")
    if not reader.schema().has_table("task_attachments"):
        return []
    select = _select(reader, "task_attachments", wanted)
    rows = reader.execute(
        f"SELECT {select} FROM task_attachments WHERE task_id = ? ORDER BY created_at ASC",
        (task_id,),
    )
    return BoardReader.rows_as_dicts(wanted, rows)
