"""Shared application state and FastAPI dependencies."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dataclasses import dataclass

from fastapi import Request

from ..config import settings
from ..hermes.health import HealthMonitor, HealthSnapshot
from ..hermes.proxy import HermesClient
from ..hermes.queries.fanout import cache
from ..hermes.readdb import readers
from ..hermes.registry import BoardRegistry, registry
from ..stream import protocol
from ..stream.hub import hub
from ..stream.tailer import Tailer

log = logging.getLogger(__name__)


@dataclass(slots=True)
class AppState:
    client: HermesClient
    health: HealthMonitor
    registry: BoardRegistry
    tailer: Tailer


async def _rescan_loop(reg: BoardRegistry, client: HermesClient) -> None:
    """Keep the board registry fresh, and fold in Hermes' advisory board list."""
    while True:
        try:
            reg.scan()
        except Exception:  # pragma: no cover - the loop must never die
            log.exception("board rescan failed")
        try:
            payload = await client.get_json("/boards")
            boards = payload.get("boards") if isinstance(payload, dict) else None
            if isinstance(boards, list):
                reg.set_advisory(boards)
        except Exception:
            # Hermes being down is normal and must not disturb the filesystem scan.
            pass
        await asyncio.sleep(settings.registry_rescan_seconds)


@asynccontextmanager
async def lifespan_state() -> AsyncIterator[AppState]:
    client = HermesClient()
    health = HealthMonitor(client)
    registry.scan(force=True)
    log.info("discovered %s", registry.summary())

    tailer = Tailer(registry, hub)

    def on_hermes_change(snapshot: HealthSnapshot) -> None:
        # Every browser needs to know the moment writes become available or stop being.
        hub.broadcast(None, protocol.hermes_state(snapshot.to_dict()))
        cache.invalidate()

    health.on_change(on_hermes_change)

    await health.start()
    await tailer.start()
    rescan = asyncio.create_task(_rescan_loop(registry, client), name="board-rescan")

    state = AppState(client=client, health=health, registry=registry, tailer=tailer)
    try:
        yield state
    finally:
        rescan.cancel()
        try:
            await rescan
        except asyncio.CancelledError:
            pass
        await tailer.stop()
        await health.stop()
        await client.aclose()
        readers.close_all()


def get_state(request: Request) -> AppState:
    return request.app.state.flightdeck
