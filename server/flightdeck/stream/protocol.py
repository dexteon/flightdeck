"""Frame shapes for the Flightdeck WebSocket at ``/ws``.

One socket carries every board. Hermes pins a board per socket at handshake, which is
precisely the limitation Flightdeck exists to remove.

Server frames
    ``hello``         on connect: board census, Hermes state, current cursors
    ``events``        new ``task_events`` rows for one board, batched per tick
    ``tasks``         current rows for the tasks those events touched
    ``log``           appended bytes from a worker log being followed
    ``board_state``   a board became available or unavailable
    ``hermes_state``  the UP/DEGRADED/DOWN machine changed
    ``resync``        your cursor is older than our buffer; refetch that board
    ``pong``

Client frames
    ``subscribe``     ``{boards: ["*"] | [slug], since: {slug: cursor}}``
    ``unsubscribe``   ``{boards: [slug]}``
    ``follow_log``    ``{board, task_id}``  start or switch the followed log
    ``unfollow_log``  ``{}``
    ``ping``
"""

from __future__ import annotations

from typing import Any

ALL_BOARDS = "*"


def hello(
    *,
    boards: list[dict[str, Any]],
    cursors: dict[str, int],
    hermes: dict[str, Any],
    stale_heartbeat_seconds: int,
) -> dict[str, Any]:
    return {
        "type": "hello",
        "boards": boards,
        "cursors": cursors,
        "hermes": hermes,
        "stale_heartbeat_seconds": stale_heartbeat_seconds,
    }


def events(board: str, rows: list[dict[str, Any]], cursor: int) -> dict[str, Any]:
    return {"type": "events", "board": board, "events": rows, "cursor": cursor}


def tasks(board: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "tasks", "board": board, "tasks": rows}


def log(board: str, task_id: str, chunk: str, offset: int, *, rotated: bool = False) -> dict[str, Any]:
    return {
        "type": "log",
        "board": board,
        "task_id": task_id,
        "chunk": chunk,
        "offset": offset,
        "rotated": rotated,
    }


def board_state(board: str, state: str, reason: str | None) -> dict[str, Any]:
    return {"type": "board_state", "board": board, "state": state, "reason": reason}


def hermes_state(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {"type": "hermes_state", "hermes": snapshot}


def resync(board: str, cursor: int, reason: str) -> dict[str, Any]:
    return {"type": "resync", "board": board, "cursor": cursor, "reason": reason}


def pong() -> dict[str, Any]:
    return {"type": "pong"}
