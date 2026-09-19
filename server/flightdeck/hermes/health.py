"""Is Hermes up, and are writes allowed?

Three states:

``UP``        reads and writes both work.
``DEGRADED``  the dashboard answers but authentication is broken. Reads still work,
              because reads never touch Hermes.
``DOWN``      the dashboard is unreachable. Two consecutive failures are required, which
              debounces an ordinary dashboard restart into a blip rather than an alarm.

The degraded-mode contract (Hermes down means read-only, never a blank page) is
structurally guaranteed rather than carefully maintained: nothing on the read path calls
this module's client.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from ..config import settings
from .proxy import HermesAuthError, HermesClient, HermesUnreachable

log = logging.getLogger(__name__)

State = Literal["UP", "DEGRADED", "DOWN"]

Listener = Callable[["HealthSnapshot"], Awaitable[None] | None]


@dataclass(frozen=True, slots=True)
class HealthSnapshot:
    state: State
    last_ok_at: float | None
    last_error: str | None
    reason: str | None

    @property
    def writes_enabled(self) -> bool:
        return self.state == "UP"

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "writes_enabled": self.writes_enabled,
            "last_ok_at": self.last_ok_at,
            "last_error": self.last_error,
            "reason": self.reason,
        }


class HealthMonitor:
    def __init__(self, client: HermesClient) -> None:
        self._client = client
        self._state: State = "DOWN"
        self._last_ok_at: float | None = None
        self._last_error: str | None = None
        self._reason: str | None = "not probed yet"
        self._consecutive_failures = 0
        self._listeners: list[Listener] = []
        self._task: asyncio.Task[None] | None = None

    # -- access ---------------------------------------------------------------

    def snapshot(self) -> HealthSnapshot:
        return HealthSnapshot(
            state=self._state,
            last_ok_at=self._last_ok_at,
            last_error=self._last_error,
            reason=self._reason,
        )

    @property
    def writes_enabled(self) -> bool:
        return self._state == "UP"

    def on_change(self, listener: Listener) -> None:
        self._listeners.append(listener)

    # -- lifecycle ------------------------------------------------------------

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="hermes-health")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while True:
            try:
                await self.probe_once()
            except Exception:  # pragma: no cover - the loop must never die
                log.exception("health probe raised")
            await asyncio.sleep(settings.health_probe_seconds)

    # -- probing --------------------------------------------------------------

    async def probe_once(self) -> HealthSnapshot:
        try:
            await self._client.probe()
        except HermesAuthError as exc:
            self._consecutive_failures = 0
            return await self._set("DEGRADED", str(exc), "auth_rejected")
        except HermesUnreachable as exc:
            message = str(exc)
            if "not found in the dashboard shell" in message:
                self._consecutive_failures = 0
                return await self._set("DEGRADED", message, "token_scrape_failed")
            self._consecutive_failures += 1
            if self._consecutive_failures >= settings.health_down_after_failures:
                return await self._set("DOWN", message, "unreachable")
            return self.snapshot()
        except Exception as exc:
            self._consecutive_failures += 1
            if self._consecutive_failures >= settings.health_down_after_failures:
                return await self._set("DOWN", f"{type(exc).__name__}: {exc}", "error")
            return self.snapshot()

        self._consecutive_failures = 0
        self._last_ok_at = time.time()
        return await self._set("UP", None, None)

    async def mark_up(self) -> None:
        """A successful proxied write proves Hermes is up. Do not wait for the probe."""
        self._consecutive_failures = 0
        self._last_ok_at = time.time()
        await self._set("UP", None, None)

    async def _set(self, state: State, error: str | None, reason: str | None) -> HealthSnapshot:
        changed = state != self._state
        self._state = state
        self._last_error = error
        self._reason = reason
        snapshot = self.snapshot()
        if changed:
            log.info("hermes state -> %s (%s)", state, reason or "ok")
            for listener in self._listeners:
                try:
                    result = listener(snapshot)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:  # pragma: no cover - a listener must not break health
                    log.exception("health listener failed")
        return snapshot
