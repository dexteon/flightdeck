"""``/api/health``: the one endpoint that says whether anything works.

Carries the Hermes state machine, the board census (so the UI can say "13 of 14
reporting"), and the per-board schema fingerprints that act as the upstream-drift alarm.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends

from ..config import settings
from ..hermes import paths
from .deps import AppState, get_state

router = APIRouter(tags=["health"])


def _fts5_available() -> bool:
    try:
        conn = sqlite3.connect(":memory:")
    except sqlite3.Error:
        return False
    try:
        options = {row[0] for row in conn.execute("PRAGMA compile_options")}
        return "ENABLE_FTS5" in options
    except sqlite3.Error:
        return False
    finally:
        conn.close()


@router.get("/health")
async def health(state: AppState = Depends(get_state)) -> dict[str, Any]:
    return {
        "ok": True,
        "version": "0.1.0",
        "hermes": {
            **state.health.snapshot().to_dict(),
            "url": state.client.base_url,
            "token_source": state.client.tokens.source,
            "token_error": state.client.tokens.last_error,
        },
        "boards": state.registry.summary(),
        "schema_fingerprints": state.registry.fingerprints(),
        "paths": {
            "hermes_root": str(paths.hermes_root()),
            "kanban_home": str(paths.kanban_home()),
            "default_board_db": str(paths.default_board_db()),
        },
        "fts5": _fts5_available(),
        "settings": {
            "stale_heartbeat_seconds": settings.stale_heartbeat_seconds,
        },
    }


@router.get("/boards")
async def list_boards(state: AppState = Depends(get_state)) -> dict[str, Any]:
    boards = state.registry.all()
    return {
        "boards": [b.to_dict() for b in boards],
        "summary": state.registry.summary(),
    }
