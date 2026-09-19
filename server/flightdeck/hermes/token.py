"""Getting a Hermes dashboard session token.

Hermes mints ``_SESSION_TOKEN`` per process (``hermes_cli/web_server.py:307-311``) and
injects it into the served SPA shell as ``window.__HERMES_SESSION_TOKEN__``
(``web_server_dashboard.py:155``). ``GET /`` is unauthenticated, so the token can be read
off the page and replayed as ``X-Hermes-Session-Token``. Verified live: a 43-character
token unlocked ``GET /api/plugins/kanban/boards``.

The token rotates every time the dashboard process restarts, so it is never cached
forever. Refresh is single-flight: ten concurrent 401s cause exactly one re-scrape.

The token stays server-side. It is never sent to our own frontend.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re

import httpx

log = logging.getLogger(__name__)

# Accept single or double quotes, and the JSON-embedded form some builds emit.
_TOKEN_RE = re.compile(
    r"__HERMES_SESSION_TOKEN__\s*[:=]\s*[\"']([A-Za-z0-9_\-=]{16,128})[\"']"
)


class TokenUnavailable(RuntimeError):
    """The session token could not be obtained."""


class TokenProvider:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._cached: str | None = None
        self._lock = asyncio.Lock()
        self._from_env = False
        self._last_error: str | None = None

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def source(self) -> str:
        if self._from_env:
            return "env"
        return "scraped" if self._cached else "none"

    def invalidate(self) -> None:
        """Drop the cached token. A token set by env var is permanent, so it stays."""
        if not self._from_env:
            self._cached = None

    async def get(self, client: httpx.AsyncClient) -> str:
        if self._cached:
            return self._cached
        async with self._lock:
            # Another waiter may have refreshed while we queued on the lock.
            if self._cached:
                return self._cached
            self._cached = await self._resolve(client)
            return self._cached

    async def _resolve(self, client: httpx.AsyncClient) -> str:
        explicit = os.environ.get("HERMES_DASHBOARD_SESSION_TOKEN", "").strip()
        if explicit:
            self._from_env = True
            self._last_error = None
            return explicit

        try:
            response = await client.get(f"{self._base_url}/")
        except httpx.HTTPError as exc:
            self._last_error = f"dashboard unreachable: {exc}"
            raise TokenUnavailable(self._last_error) from exc

        if response.status_code != 200:
            self._last_error = f"GET / returned {response.status_code}"
            raise TokenUnavailable(self._last_error)

        match = _TOKEN_RE.search(response.text)
        if match is None:
            self._last_error = (
                "__HERMES_SESSION_TOKEN__ not found in the dashboard shell; "
                "set HERMES_DASHBOARD_SESSION_TOKEN to supply it manually"
            )
            raise TokenUnavailable(self._last_error)

        self._last_error = None
        return match.group(1)
