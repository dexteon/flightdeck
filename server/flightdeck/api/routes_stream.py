"""The Flightdeck WebSocket at ``/ws``.

One socket per browser, carrying every board it subscribes to. Reader and writer run as
separate tasks so a client that stops reading cannot block the tailer: its bounded queue
fills, the hub marks it dropped, and it is told to resync.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..config import settings
from ..stream import protocol
from ..stream.hub import Connection, hub

log = logging.getLogger(__name__)

router = APIRouter()

PING_SECONDS = 20.0


@router.websocket("/ws")
async def stream(websocket: WebSocket) -> None:
    await websocket.accept()
    state = websocket.app.state.flightdeck
    conn = hub.connect()
    try:
        await websocket.send_json(
            protocol.hello(
                boards=[b.to_dict() for b in state.registry.all()],
                cursors=state.tailer.cursors(),
                hermes=state.health.snapshot().to_dict(),
                stale_heartbeat_seconds=settings.stale_heartbeat_seconds,
            )
        )
        writer = asyncio.create_task(_writer(websocket, conn))
        reader = asyncio.create_task(_reader(websocket, conn, state))
        done, pending = await asyncio.wait(
            {writer, reader}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc and not isinstance(exc, WebSocketDisconnect):
                log.warning("websocket task ended: %r", exc)
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(conn)


async def _writer(websocket: WebSocket, conn: Connection) -> None:
    while True:
        try:
            frame = await asyncio.wait_for(conn.queue.get(), timeout=PING_SECONDS)
        except TimeoutError:
            # Keepalive, and a cheap liveness check on an otherwise idle fleet.
            await websocket.send_json(protocol.pong())
            continue
        await websocket.send_json(frame)


async def _reader(websocket: WebSocket, conn: Connection, state: Any) -> None:
    while True:
        message = await websocket.receive_json()
        kind = message.get("type")

        if kind == "subscribe":
            boards = message.get("boards") or [protocol.ALL_BOARDS]
            conn.boards = set(boards)
            for slug, cursor in (message.get("since") or {}).items():
                replay = hub.replay(slug, int(cursor))
                if replay is None:
                    current = state.tailer.cursors().get(slug, 0)
                    conn.send_nowait(
                        protocol.resync(slug, current, "cursor older than buffer")
                    )
                elif replay:
                    conn.send_nowait(protocol.events(slug, replay, replay[-1]["id"]))

        elif kind == "unsubscribe":
            conn.boards -= set(message.get("boards") or [])

        elif kind == "follow_log":
            board, task_id = message.get("board"), message.get("task_id")
            conn.follow = (board, task_id) if board and task_id else None

        elif kind == "unfollow_log":
            conn.follow = None

        elif kind == "ping":
            conn.send_nowait(protocol.pong())
