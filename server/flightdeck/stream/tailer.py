"""Tail ``task_events`` across every board.

Flightdeck does not consume Hermes' ``WS /events``. That socket is itself a 0.3s poll of
this same table, so there is no freshness to gain; it pins one board per connection,
which is the limitation we exist to remove; and it dies with the dashboard, whereas
agents and the gateway keep writing to ``kanban.db`` regardless. Tailing SQLite directly
keeps live updates flowing while Hermes is down, which is the whole degraded-mode
contract.

Cadence is adaptive because most boards are idle most of the time. Watched boards and
boards with running work get 400ms; recently active boards 3s; idle boards 15s; boards in
error 30s.

Two things keep the cost down at the measured volumes:

* Cursors start at ``MAX(id)``, so the 16218 existing rows on `ai-fraud-guide` are never
  replayed.
* A tick emits one ``events`` frame and one batched ``tasks`` frame, not one per row.
  Heartbeats are 5516 of those 16218 events; per-event frames would be a render storm.

A 30s diff sweep covers field edits that emit no event at all, so the UI is self-healing
regardless of which mutations Hermes chooses to log.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from starlette.concurrency import run_in_threadpool

from ..config import settings
from ..hermes.queries import events as qe
from ..hermes.queries import tasks as qt
from ..hermes.readdb import BoardUnavailable, readers
from ..hermes.registry import BoardRegistry
from . import protocol
from .hub import Hub

log = logging.getLogger(__name__)

WATCHED_INTERVAL = 0.4
ACTIVE_INTERVAL = 3.0
IDLE_INTERVAL = 15.0
ERROR_INTERVAL = 30.0
RECENT_ACTIVITY_SECONDS = 600.0
DIFF_SWEEP_SECONDS = 30.0
EVENT_BATCH = 500

#: Columns the diff sweep compares. Cheap to read, and covers everything a card shows.
DIFF_COLUMNS: tuple[str, ...] = (
    "id",
    "status",
    "priority",
    "assignee",
    "title",
    "started_at",
    "completed_at",
    "last_heartbeat_at",
    "current_run_id",
    "worker_pid",
    "block_kind",
    "consecutive_failures",
)


@dataclass(slots=True)
class BoardCursor:
    cursor: int = 0
    next_due: float = 0.0
    last_event_at: float = 0.0
    last_sweep: float = 0.0
    failing: bool = False
    snapshot: dict[str, tuple[Any, ...]] = field(default_factory=dict)


class Tailer:
    def __init__(self, registry: BoardRegistry, hub: Hub) -> None:
        self._registry = registry
        self._hub = hub
        self._state: dict[str, BoardCursor] = {}
        self._task: asyncio.Task[None] | None = None

    # -- lifecycle ------------------------------------------------------------

    async def start(self) -> None:
        if self._task is None:
            await self.prime()
            self._task = asyncio.create_task(self._loop(), name="event-tailer")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def prime(self) -> None:
        """Start every cursor at the current head. History is never replayed."""
        for board in self._registry.available():
            state = self._state.setdefault(board.slug, BoardCursor())
            try:
                reader = readers.get(board.slug, board.db_path)
                state.cursor = await run_in_threadpool(qe.max_event_id, reader)
            except BoardUnavailable as exc:
                state.failing = True
                log.warning("cannot prime %s: %s", board.slug, exc.reason)

    def cursors(self) -> dict[str, int]:
        return {slug: state.cursor for slug, state in self._state.items()}

    # -- main loop ------------------------------------------------------------

    async def _loop(self) -> None:
        while True:
            now = time.monotonic()
            due = [b for b in self._registry.available() if self._due(b.slug, now)]
            for board in due:
                try:
                    await self._tick(board.slug, board.db_path)
                except Exception:  # pragma: no cover - the loop must never die
                    log.exception("tailer tick failed for %s", board.slug)
            await asyncio.sleep(0.1)

    def _due(self, slug: str, now: float) -> bool:
        return self._state.setdefault(slug, BoardCursor()).next_due <= now

    def _reschedule(self, slug: str, *, has_running: bool) -> None:
        state = self._state[slug]
        now = time.monotonic()
        if state.failing:
            interval = ERROR_INTERVAL
        elif self._hub.watchers(slug) or has_running:
            interval = WATCHED_INTERVAL
        elif now - state.last_event_at < RECENT_ACTIVITY_SECONDS:
            interval = ACTIVE_INTERVAL
        else:
            interval = IDLE_INTERVAL
        state.next_due = now + interval

    # -- one board, one tick --------------------------------------------------

    async def _tick(self, slug: str, db_path: Any) -> None:
        state = self._state.setdefault(slug, BoardCursor())
        reader = readers.get(slug, db_path)

        try:
            rows = await run_in_threadpool(qe.events_since, reader, state.cursor, EVENT_BATCH)
        except BoardUnavailable as exc:
            if not state.failing:
                state.failing = True
                self._hub.broadcast(None, protocol.board_state(slug, "unavailable", exc.reason))
                log.warning("board %s went unavailable: %s", slug, exc.reason)
            self._reschedule(slug, has_running=False)
            return

        if state.failing:
            state.failing = False
            self._hub.broadcast(None, protocol.board_state(slug, "available", None))

        has_running = False
        if rows:
            state.cursor = rows[-1]["id"]
            state.last_event_at = time.monotonic()
            self._hub.remember(slug, rows)
            self._hub.broadcast(slug, protocol.events(slug, rows, state.cursor))

            touched = sorted({r["task_id"] for r in rows if r.get("task_id")})
            if touched:
                refreshed = await self._read_tasks(reader, touched)
                if refreshed:
                    has_running = any(t.get("status") == "running" for t in refreshed)
                    self._hub.broadcast(slug, protocol.tasks(slug, refreshed))

        now = time.monotonic()
        if now - state.last_sweep >= DIFF_SWEEP_SECONDS and self._hub.watchers(slug):
            state.last_sweep = now
            changed, running = await self._diff_sweep(reader, state)
            has_running = has_running or running
            if changed:
                self._hub.broadcast(slug, protocol.tasks(slug, changed))

        self._reschedule(slug, has_running=has_running)

    async def _read_tasks(self, reader: Any, task_ids: list[str]) -> list[dict[str, Any]]:
        """One batched read for every task the tick's events touched."""

        def read() -> list[dict[str, Any]]:
            marks = ", ".join("?" for _ in task_ids)
            select = ", ".join(
                f'"{c}"' for c in reader.select_list("tasks", qt.TASK_COLUMNS)
            )
            rows = reader.execute(
                f"SELECT {select} FROM tasks WHERE id IN ({marks})", task_ids
            )
            return reader.rows_as_dicts(qt.TASK_COLUMNS, rows)

        try:
            return await run_in_threadpool(read)
        except BoardUnavailable:
            return []

    async def _diff_sweep(
        self, reader: Any, state: BoardCursor
    ) -> tuple[list[dict[str, Any]], bool]:
        """Catch mutations that emit no event, for example a priority edit.

        About 5ms at 1098 rows, and only for boards someone is actually watching.
        """

        def read() -> list[dict[str, Any]]:
            select = ", ".join(
                f'"{c}"' for c in reader.select_list("tasks", DIFF_COLUMNS)
            )
            rows = reader.execute(f"SELECT {select} FROM tasks")
            return reader.rows_as_dicts(DIFF_COLUMNS, rows)

        try:
            rows = await run_in_threadpool(read)
        except BoardUnavailable:
            return [], False

        changed: list[dict[str, Any]] = []
        seen: dict[str, tuple[Any, ...]] = {}
        running = False
        for row in rows:
            key = tuple(row[c] for c in DIFF_COLUMNS)
            seen[row["id"]] = key
            if row.get("status") == "running":
                running = True
            if state.snapshot.get(row["id"]) != key:
                changed.append(row)

        first_pass = not state.snapshot
        state.snapshot = seen
        # The first sweep has nothing to compare against, so everything looks changed.
        return ([] if first_pass else changed), running
