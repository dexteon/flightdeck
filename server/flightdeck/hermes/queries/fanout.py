"""Run a read across every board and merge the results.

Deliberately not ``ATTACH``. Three reasons, in order of how badly each would bite:

1. ``SQLITE_MAX_ATTACHED`` defaults to 10 and there are 14 boards. It does not fit
   without recompiling SQLite.
2. One locked or corrupt file would poison the whole query. Fanning out degrades to
   "13 of 14 reporting" instead, which is the difference between a partial answer and
   no answer.
3. Schema drift is per board. ``nrt-unify`` already has a ``tasks.task_source`` column
   the others lack, so a ``UNION ALL`` across boards would be a runtime error.

There is also nothing to win: each board returns a pre-aggregated ``GROUP BY`` of tens of
rows, so the heavy lifting stays inside SQLite and Python merges a handful of dicts.

Every result carries ``partial`` and names the boards that did not answer. A fleet view
that silently under-reports is worse than one that says what it is missing.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from starlette.concurrency import run_in_threadpool

from ..readdb import BoardReader, BoardUnavailable, readers
from ..registry import Board, BoardRegistry

log = logging.getLogger(__name__)

T = TypeVar("T")

PER_BOARD_TIMEOUT = 2.0
CACHE_TTL = 20.0


@dataclass(slots=True)
class FanoutResult(Generic[T]):
    data: dict[str, T]
    unavailable: list[dict[str, str]] = field(default_factory=list)

    @property
    def partial(self) -> bool:
        return bool(self.unavailable)

    def envelope(self, payload: Any) -> dict[str, Any]:
        return {
            "data": payload,
            "partial": self.partial,
            "unavailable": self.unavailable,
        }


async def fan_out(
    registry: BoardRegistry,
    query: Callable[[BoardReader], T],
    *,
    boards: list[Board] | None = None,
    timeout: float = PER_BOARD_TIMEOUT,
) -> FanoutResult[T]:
    targets = boards if boards is not None else registry.available()

    async def one(board: Board) -> tuple[str, T | None, str | None]:
        try:
            reader = readers.get(board.slug, board.db_path)
            value = await asyncio.wait_for(
                run_in_threadpool(query, reader), timeout=timeout
            )
            return board.slug, value, None
        except TimeoutError:
            return board.slug, None, f"timed out after {timeout}s"
        except BoardUnavailable as exc:
            return board.slug, None, exc.reason
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("fan-out query failed for %s", board.slug)
            return board.slug, None, f"{type(exc).__name__}: {exc}"

    settled = await asyncio.gather(*(one(b) for b in targets))

    data: dict[str, T] = {}
    unavailable: list[dict[str, str]] = []
    for slug, value, reason in settled:
        if reason is None:
            data[slug] = value  # type: ignore[assignment]
        else:
            unavailable.append({"slug": slug, "reason": reason})

    # Boards the registry already knows are broken belong in the same list, so callers
    # see one honest census rather than two.
    for board in registry.all():
        if board.state != "available" and not any(
            u["slug"] == board.slug for u in unavailable
        ):
            unavailable.append({"slug": board.slug, "reason": board.reason or "unavailable"})

    return FanoutResult(data=data, unavailable=unavailable)


class TTLCache:
    """Small TTL cache for aggregates, invalidated per board when events arrive."""

    def __init__(self, ttl: float = CACHE_TTL) -> None:
        self._ttl = ttl
        self._entries: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires, value = entry
        if expires < time.monotonic():
            self._entries.pop(key, None)
            return None
        return value

    def put(self, key: str, value: Any) -> None:
        self._entries[key] = (time.monotonic() + self._ttl, value)

    def invalidate(self, prefix: str = "") -> None:
        if not prefix:
            self._entries.clear()
            return
        for key in [k for k in self._entries if k.startswith(prefix)]:
            self._entries.pop(key, None)


cache = TTLCache()
