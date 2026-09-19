"""Task reads.

Every query names its columns and intersects them with what the board actually has.
This is not defensive paranoia: ``nrt-unify`` already carries a ``tasks.task_source``
column that the other thirteen boards do not, so the column set genuinely differs
board to board on this machine today.
"""

from __future__ import annotations

import time
from typing import Any

from ..readdb import BoardReader

# Ordered widest-to-narrowest by usefulness. Anything a board lacks comes back as None.
TASK_COLUMNS: tuple[str, ...] = (
    "id",
    "title",
    "body",
    "status",
    "assignee",
    "priority",
    "tenant",
    "created_by",
    "created_at",
    "started_at",
    "completed_at",
    "result",
    "workspace_kind",
    "workspace_path",
    "branch_name",
    "project_id",
    "claim_lock",
    "claim_expires",
    "worker_pid",
    "last_heartbeat_at",
    "current_run_id",
    "consecutive_failures",
    "last_failure_error",
    "max_runtime_seconds",
    "max_retries",
    "skills",
    "model_override",
    "provider_override",
    "reasoning_effort",
    "goal_mode",
    "goal_max_turns",
    "session_id",
    "block_kind",
    "block_recurrences",
)

# Hermes' own column order, from plugin_api.py:169. `archived` is opt-in.
BOARD_COLUMNS: tuple[str, ...] = (
    "triage",
    "todo",
    "scheduled",
    "ready",
    "running",
    "blocked",
    "review",
    "done",
)

ACTIVE_STATUSES: tuple[str, ...] = ("triage", "todo", "scheduled", "ready", "running", "blocked", "review")


def _select(reader: BoardReader, table: str, wanted: tuple[str, ...]) -> str:
    cols = reader.select_list(table, wanted)
    if not cols:
        raise ValueError(f"{table} has none of the requested columns")
    return ", ".join(f'"{c}"' for c in cols)


def status_counts(reader: BoardReader) -> dict[str, int]:
    rows = reader.execute("SELECT status, COUNT(*) AS n FROM tasks GROUP BY status")
    return {row["status"]: row["n"] for row in rows}


def list_tasks(
    reader: BoardReader,
    *,
    statuses: tuple[str, ...] | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[dict[str, Any]]:
    select = _select(reader, "tasks", TASK_COLUMNS)
    params: list[Any] = []
    where = ""
    if statuses:
        placeholders = ", ".join("?" for _ in statuses)
        where = f" WHERE status IN ({placeholders})"
        params.extend(statuses)
    params.extend([limit, offset])
    sql = (
        f"SELECT {select} FROM tasks{where} "
        "ORDER BY priority DESC, created_at ASC LIMIT ? OFFSET ?"
    )
    return BoardReader.rows_as_dicts(TASK_COLUMNS, reader.execute(sql, params))


def get_task(reader: BoardReader, task_id: str) -> dict[str, Any] | None:
    select = _select(reader, "tasks", TASK_COLUMNS)
    rows = reader.execute(f"SELECT {select} FROM tasks WHERE id = ?", (task_id,))
    if not rows:
        return None
    return BoardReader.rows_as_dicts(TASK_COLUMNS, rows)[0]


def running_tasks(reader: BoardReader) -> list[dict[str, Any]]:
    """Everything currently claimed. Feeds the fleet-wide running strip."""
    return list_tasks(reader, statuses=("running",), limit=200)


def stale_running(reader: BoardReader, threshold_seconds: int) -> list[dict[str, Any]]:
    """Running tasks whose heartbeat has gone quiet.

    Hermes hardcodes 120s in the UI (``ui.tsx:128``); the threshold is a setting here.
    A NULL heartbeat on a task that started more than the threshold ago also counts:
    a worker that never checked in is exactly as wedged as one that stopped.
    """
    cutoff = int(time.time()) - threshold_seconds
    select = _select(reader, "tasks", TASK_COLUMNS)
    sql = (
        f"SELECT {select} FROM tasks WHERE status = 'running' AND ("
        "  (last_heartbeat_at IS NOT NULL AND last_heartbeat_at < ?)"
        "  OR (last_heartbeat_at IS NULL AND started_at IS NOT NULL AND started_at < ?)"
        ") ORDER BY COALESCE(last_heartbeat_at, started_at) ASC"
    )
    rows = reader.execute(sql, (cutoff, cutoff))
    return BoardReader.rows_as_dicts(TASK_COLUMNS, rows)


def counts_by_assignee(reader: BoardReader) -> list[dict[str, Any]]:
    rows = reader.execute(
        "SELECT assignee, status, COUNT(*) AS n FROM tasks "
        "WHERE assignee IS NOT NULL GROUP BY assignee, status"
    )
    return [dict(row) for row in rows]


def oldest_ready_age(reader: BoardReader) -> int | None:
    """Seconds the longest-waiting ready task has been queued, or None if none are."""
    rows = reader.execute(
        "SELECT MIN(created_at) AS oldest FROM tasks WHERE status = 'ready'"
    )
    oldest = rows[0]["oldest"] if rows else None
    if oldest is None:
        return None
    return max(0, int(time.time()) - int(oldest))
