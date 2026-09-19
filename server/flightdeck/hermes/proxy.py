"""The only code that knows the Hermes REST API exists.

Every mutation Flightdeck performs goes through here, so Hermes stays the owner of task
lifecycle and of the ``BEGIN IMMEDIATE`` + compare-and-swap claim protocol.

Error handling is deliberately blunt:

* A 401 means the dashboard restarted and rotated its token. Invalidate, refresh, retry
  **exactly once**, then give up. Never loop.
* Any other non-2xx passes through with the Hermes status and body intact. The UI needs
  the 400 and 409 text verbatim, and a 409 in particular means a claim moved under us,
  which must never be auto-retried.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..config import settings
from .token import TokenProvider, TokenUnavailable

log = logging.getLogger(__name__)

API_PREFIX = "/api/plugins/kanban"


class HermesError(RuntimeError):
    """Hermes returned a non-2xx we are passing through to the caller."""

    def __init__(self, status_code: int, detail: Any, *, path: str) -> None:
        super().__init__(f"{path} -> {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail
        self.path = path


class HermesAuthError(HermesError):
    """Still 401 after a fresh token. Credentials are broken, not stale."""


class HermesUnreachable(RuntimeError):
    """The dashboard is not answering at all."""


class HermesClient:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or settings.hermes_url).rstrip("/")
        self._tokens = TokenProvider(self.base_url)
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(connect=2.0, read=30.0, write=60.0, pool=5.0),
            follow_redirects=False,
        )

    @property
    def tokens(self) -> TokenProvider:
        return self._tokens

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- core request ---------------------------------------------------------

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
        stream_response: bool = False,
    ) -> httpx.Response:
        """Call a kanban plugin endpoint. ``path`` is relative to ``API_PREFIX``."""
        url = f"{API_PREFIX}{path}"
        response = await self._send(
            method, url, params=params, json=json, content=content, headers=headers
        )
        if response.status_code == 401:
            # Stale token: the dashboard restarted. One refresh, one retry, no loop.
            self._tokens.invalidate()
            response = await self._send(
                method, url, params=params, json=json, content=content, headers=headers
            )
            if response.status_code == 401:
                raise HermesAuthError(401, _detail(response), path=url)

        if response.status_code >= 400 and not stream_response:
            raise HermesError(response.status_code, _detail(response), path=url)
        return response

    async def _send(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None,
        json: Any,
        content: bytes | None,
        headers: dict[str, str] | None,
    ) -> httpx.Response:
        try:
            token = await self._tokens.get(self._client)
        except TokenUnavailable as exc:
            raise HermesUnreachable(str(exc)) from exc

        merged = {"X-Hermes-Session-Token": token}
        if headers:
            merged.update(headers)
        try:
            return await self._client.request(
                method, url, params=params, json=json, content=content, headers=merged
            )
        except httpx.HTTPError as exc:
            raise HermesUnreachable(f"{type(exc).__name__}: {exc}") from exc

    # -- convenience ----------------------------------------------------------

    async def get_json(self, path: str, **params: Any) -> Any:
        clean = {k: v for k, v in params.items() if v is not None}
        response = await self.request("GET", path, params=clean or None)
        return response.json()

    async def post_json(self, path: str, payload: Any = None, **params: Any) -> Any:
        clean = {k: v for k, v in params.items() if v is not None}
        response = await self.request("POST", path, json=payload, params=clean or None)
        return _json_or_none(response)

    async def patch_json(self, path: str, payload: Any) -> Any:
        response = await self.request("PATCH", path, json=payload)
        return _json_or_none(response)

    async def delete_json(self, path: str, **params: Any) -> Any:
        clean = {k: v for k, v in params.items() if v is not None}
        response = await self.request("DELETE", path, params=clean or None)
        return _json_or_none(response)

    # -- probe used by the health state machine -------------------------------

    async def probe(self) -> None:
        """Cheap authenticated call, so it validates reachability and the token."""
        await self.request("GET", "/config")


def _detail(response: httpx.Response) -> Any:
    try:
        body = response.json()
    except ValueError:
        return response.text[:500]
    if isinstance(body, dict) and "detail" in body:
        return body["detail"]
    return body


def _json_or_none(response: httpx.Response) -> Any:
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return None
