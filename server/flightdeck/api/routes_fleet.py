"""Fleet-wide reads: every board at once.

This is the thing Hermes structurally cannot do. Its board switcher shows one board at a
time, so there has never been a view of the 14 boards and 1279 tasks as a whole.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, Query

from ..config import settings
from ..hermes.queries import events as qe
from ..hermes.queries import tasks as qt
from ..hermes.queries.fanout import fan_out
from ..hermes.readdb import BoardReader
from .deps import AppState, get_state

router = APIRouter(tags=["fleet"])


def _heartbeat_age(task: dict[str, Any], now: int) -> int | None:
    stamp = task.get("last_heartbeat_at") or task.get("started_at")
    if stamp is None:
        return None
    return max(0, now - int(stamp))


@router.get("/fleet")
async def fleet(state: AppState = Depends(get_state)) -> dict[str, Any]:
    """One tile per board plus a fleet-wide rollup."""
    now = int(time.time())
    threshold = settings.stale_heartbeat_seconds

    def per_board(reader: BoardReader) -> dict[str, Any]:
        counts = qt.status_counts(reader)
        running = qt.running_tasks(reader)
        stale = qt.stale_running(reader, threshold)
        return {
            "counts": counts,
            "total": sum(counts.values()),
            "running": len(running),
            "stale": len(stale),
            "oldest_ready_age": qt.oldest_ready_age(reader),
        }

    result = await fan_out(state.registry, per_board)

    tiles = []
    rollup = {"total": 0, "running": 0, "stale": 0, "counts": {}}
    for board in state.registry.all():
        stats = result.data.get(board.slug)
        tile = {
            **board.to_dict(),
            "stats": stats,
        }
        tiles.append(tile)
        if stats is None:
            continue
        rollup["total"] += stats["total"]
        rollup["running"] += stats["running"]
        rollup["stale"] += stats["stale"]
        for status, n in stats["counts"].items():
            rollup["counts"][status] = rollup["counts"].get(status, 0) + n

    return {
        "boards": tiles,
        "rollup": rollup,
        "now": now,
        "stale_heartbeat_seconds": threshold,
        "partial": result.partial,
        "unavailable": result.unavailable,
        "hermes": state.health.snapshot().to_dict(),
    }


@router.get("/fleet/running")
async def fleet_running(state: AppState = Depends(get_state)) -> dict[str, Any]:
    """Every claimed task across every board, newest claim first.

    Includes ``stale`` per row rather than only counting them, because on this fleet a
    claimed task is very often a zombie: the worker died and nothing reclaimed the row.
    """
    now = int(time.time())
    threshold = settings.stale_heartbeat_seconds

    def per_board(reader: BoardReader) -> list[dict[str, Any]]:
        rows = qt.running_tasks(reader)
        runs = {r["task_id"]: r for r in qe.open_runs(reader)}
        for row in rows:
            age = _heartbeat_age(row, now)
            row["heartbeat_age"] = age
            row["stale"] = age is not None and age > threshold
            row["run"] = runs.get(row["id"])
        return rows

    result = await fan_out(state.registry, per_board)

    workers: list[dict[str, Any]] = []
    for slug, rows in result.data.items():
        for row in rows:
            workers.append({"board": slug, **row})
    workers.sort(key=lambda w: w.get("started_at") or 0, reverse=True)

    return {
        "workers": workers,
        "count": len(workers),
        "stale_count": sum(1 for w in workers if w["stale"]),
        "now": now,
        "stale_heartbeat_seconds": threshold,
        "partial": result.partial,
        "unavailable": result.unavailable,
    }


@router.get("/fleet/alerts")
async def fleet_alerts(
    state: AppState = Depends(get_state),
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    """What needs a human: stale claims, blocked work, and long-queued ready tasks."""
    now = int(time.time())
    threshold = settings.stale_heartbeat_seconds

    def per_board(reader: BoardReader) -> dict[str, Any]:
        stale = qt.stale_running(reader, threshold)
        blocked = qt.list_tasks(reader, statuses=("blocked",), limit=limit)
        return {"stale": stale, "blocked": blocked, "oldest_ready": qt.oldest_ready_age(reader)}

    result = await fan_out(state.registry, per_board)

    alerts: list[dict[str, Any]] = []
    for slug, payload in result.data.items():
        for task in payload["stale"]:
            alerts.append(
                {
                    "kind": "stale_claim",
                    "severity": "error",
                    "board": slug,
                    "task_id": task["id"],
                    "title": task["title"],
                    "detail": f"no heartbeat for {_heartbeat_age(task, now)}s",
                    "task": task,
                }
            )
        for task in payload["blocked"]:
            alerts.append(
                {
                    "kind": "blocked",
                    "severity": "warning",
                    "board": slug,
                    "task_id": task["id"],
                    "title": task["title"],
                    "detail": task.get("block_kind") or "blocked",
                    "task": task,
                }
            )
        age = payload["oldest_ready"]
        if age is not None and age > 86400:
            alerts.append(
                {
                    "kind": "stuck_queue",
                    "severity": "warning",
                    "board": slug,
                    "task_id": None,
                    "title": f"{slug} has ready work queued {age // 86400}d",
                    "detail": f"oldest ready task waiting {age}s",
                    "task": None,
                }
            )

    order = {"error": 0, "warning": 1, "info": 2}
    alerts.sort(key=lambda a: (order.get(a["severity"], 9), a["board"]))

    return {
        "alerts": alerts[:limit],
        "count": len(alerts),
        "partial": result.partial,
        "unavailable": result.unavailable,
    }


@router.get("/fleet/queue")
async def fleet_queue(
    state: AppState = Depends(get_state),
    status: list[str] | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
) -> dict[str, Any]:
    """One queue across every board, in Hermes' own priority order."""
    statuses = tuple(status) if status else qt.ACTIVE_STATUSES

    def per_board(reader: BoardReader) -> list[dict[str, Any]]:
        return qt.list_tasks(reader, statuses=statuses, limit=limit)

    result = await fan_out(state.registry, per_board)

    rows: list[dict[str, Any]] = []
    for slug, tasks in result.data.items():
        for task in tasks:
            rows.append({"board": slug, **task})
    rows.sort(
        key=lambda t: (-(t.get("priority") or 0), t.get("created_at") or 0)
    )

    return {
        "tasks": rows[:limit],
        "count": len(rows),
        "statuses": list(statuses),
        "partial": result.partial,
        "unavailable": result.unavailable,
    }
