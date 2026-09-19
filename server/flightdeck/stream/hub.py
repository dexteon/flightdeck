"""Fan-out from the tailer to connected browsers.

A slow client must never be able to stall the tailer, so every connection owns a bounded
queue. When it overflows, the client is told to resync rather than being waited on: the
tailer keeps a per-board ring buffer, and a client whose cursor has fallen out of that
buffer refetches the board instead of replaying.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Any

from .protocol import ALL_BOARDS

log = logging.getLogger(__name__)

QUEUE_SIZE = 256
RING_SIZE = 2000


class Connection:
    """One browser socket."""

    _next_id = 0

    def __init__(self) -> None:
        Connection._next_id += 1
        self.id = Connection._next_id
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=QUEUE_SIZE)
        self.boards: set[str] = set()
        self.follow: tuple[str, str] | None = None
        self.dropped = False

    def watches(self, board: str) -> bool:
        return ALL_BOARDS in self.boards or board in self.boards

    def send_nowait(self, frame: dict[str, Any]) -> bool:
        """Queue a frame. False means the client is too slow and needs a resync."""
        try:
            self.queue.put_nowait(frame)
            return True
        except asyncio.QueueFull:
            self.dropped = True
            return False


class Hub:
    def __init__(self) -> None:
        self._connections: set[Connection] = set()
        self._ring: dict[str, deque[dict[str, Any]]] = {}

    # -- membership -----------------------------------------------------------

    def connect(self) -> Connection:
        conn = Connection()
        self._connections.add(conn)
        return conn

    def disconnect(self, conn: Connection) -> None:
        self._connections.discard(conn)

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    def watchers(self, board: str) -> int:
        """How many clients care about this board. Drives the tailer's cadence."""
        return sum(1 for c in self._connections if c.watches(board))

    def any_watchers(self) -> bool:
        return bool(self._connections)

    def followed_logs(self) -> set[tuple[str, str]]:
        return {c.follow for c in self._connections if c.follow is not None}

    # -- buffering and delivery ----------------------------------------------

    def remember(self, board: str, events: list[dict[str, Any]]) -> None:
        ring = self._ring.setdefault(board, deque(maxlen=RING_SIZE))
        ring.extend(events)

    def replay(self, board: str, since: int) -> list[dict[str, Any]] | None:
        """Events after ``since`` from the ring, or None if it cannot be satisfied."""
        ring = self._ring.get(board)
        if not ring:
            return None
        if ring[0]["id"] > since + 1:
            # The client missed more than we still hold.
            return None
        return [event for event in ring if event["id"] > since]

    def broadcast(self, board: str | None, frame: dict[str, Any]) -> list[Connection]:
        """Send to every interested connection. Returns the ones that overflowed."""
        overflowed: list[Connection] = []
        for conn in list(self._connections):
            if board is not None and not conn.watches(board):
                continue
            if not conn.send_nowait(frame):
                overflowed.append(conn)
        return overflowed

    def send_to(self, conn: Connection, frame: dict[str, Any]) -> bool:
        return conn.send_nowait(frame)


hub = Hub()
