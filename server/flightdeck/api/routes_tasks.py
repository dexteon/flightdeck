"""Per-board task reads, straight from SQLite.

These never touch Hermes, which is what makes the board keep working when the dashboard
is not running.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from ..config import settings
from ..hermes.queries import events as qe
from ..hermes.queries import tasks as qt
from ..hermes.readdb import BoardReader, BoardUnavailable, readers
from ..hermes.verbs import allowed_targets
from .deps import AppState, get_state

router = APIRouter(tags=["tasks"])


def _reader(state: AppState, board: str) -> BoardReader:
    try:
        entry = state.registry.require(board)
    except BoardUnavailable as exc:
        raise HTTPException(status_code=404, detail=exc.reason) from exc
    return readers.get(entry.slug, entry.db_path)


@router.get("/boards/{board}/tasks")
async def board_tasks(
    board: str,
    state: AppState = Depends(get_state),
    status: list[str] | None = Query(None),
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    reader = _reader(state, board)
    statuses = tuple(status) if status else None
    try:
        rows = await run_in_threadpool(
            qt.list_tasks, reader, statuses=statuses, limit=limit, offset=offset
        )
        counts = await run_in_threadpool(qt.status_counts, reader)
        cursor = await run_in_threadpool(qe.max_event_id, reader)
    except BoardUnavailable as exc:
        raise HTTPException(status_code=503, detail=exc.reason) from exc

    # `counts` comes from a GROUP BY over the whole table, so it is the true total
    # regardless of how many rows this page returned. Reporting "469 of 500" when the
    # board holds 1098 tasks would be a count that lies.
    total = sum(counts.values())
    return {
        "board": board,
        "tasks": rows,
        "counts": counts,
        "columns": list(qt.BOARD_COLUMNS),
        "cursor": cursor,
        "total": total,
        "returned": len(rows),
        "truncated": len(rows) < total and not statuses,
        "limit": limit,
        "now": int(time.time()),
        "stale_heartbeat_seconds": settings.stale_heartbeat_seconds,
    }


@router.get("/boards/{board}/tasks/{task_id}")
async def task_detail(
    board: str, task_id: str, state: AppState = Depends(get_state)
) -> dict[str, Any]:
    """Everything about one task, assembled from five tables in one round trip."""
    reader = _reader(state, board)

    def read() -> dict[str, Any] | None:
        task = qt.get_task(reader, task_id)
        if task is None:
            return None
        link_rows = qe.links_for_tasks(reader, [task_id])
        return {
            "task": task,
            "runs": qe.runs_for_task(reader, task_id),
            "events": qe.events_for_task(reader, task_id),
            "comments": qe.comments_for_task(reader, task_id),
            "attachments": qe.attachments_for_task(reader, task_id),
            "links": {
                "parents": [r["parent_id"] for r in link_rows if r["child_id"] == task_id],
                "children": [r["child_id"] for r in link_rows if r["parent_id"] == task_id],
            },
        }

    try:
        detail = await run_in_threadpool(read)
    except BoardUnavailable as exc:
        raise HTTPException(status_code=503, detail=exc.reason) from exc

    if detail is None:
        raise HTTPException(status_code=404, detail=f"no task {task_id} on board {board}")

    status = detail["task"].get("status") or ""
    return {
        "board": board,
        **detail,
        # Precomputed so the UI never has to encode the transition rules itself.
        "allowed_transitions": allowed_targets(status),
        "hermes_url": f"{state.client.base_url}/kanban",
        "now": int(time.time()),
    }


@router.get("/boards/{board}/links")
async def board_links(board: str, state: AppState = Depends(get_state)) -> dict[str, Any]:
    """The dependency DAG. Measured shape is shallow: max depth 11, max fanout 8."""
    reader = _reader(state, board)
    try:
        edges = await run_in_threadpool(qe.links, reader)
        rows = await run_in_threadpool(
            qt.list_tasks, reader, statuses=None, limit=2000, offset=0
        )
    except BoardUnavailable as exc:
        raise HTTPException(status_code=503, detail=exc.reason) from exc

    linked = {e["parent_id"] for e in edges} | {e["child_id"] for e in edges}
    nodes = [
        {
            "id": t["id"],
            "title": t["title"],
            "status": t["status"],
            "assignee": t["assignee"],
            "priority": t["priority"],
        }
        for t in rows
        if t["id"] in linked
    ]
    return {"board": board, "nodes": nodes, "edges": edges}
