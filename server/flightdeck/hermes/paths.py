"""Where Hermes keeps its kanban data.

Resolution mirrors ``hermes_cli/kanban_db.py:382-390`` and ``hermes_constants.py:45-51``:
the kanban root is deliberately NOT derived from the active profile, because the board is
shared cross-profile by design.

One hard-won detail: ``C:\\Users\\user\\.hermes\\kanban.db`` exists on this machine, is
0 bytes, and is NOT the live database. It is denylisted by path here and would also fail
the size check in the registry. Both guards stay.
"""

from __future__ import annotations

import os
from pathlib import Path

# Paths that look like a board DB but are known-dead. Compared case-insensitively
# against the resolved path.
DENYLISTED_DB_PATHS: tuple[str, ...] = (
    str(Path.home() / ".hermes" / "kanban.db"),
)


def _env_path(name: str) -> Path | None:
    raw = os.environ.get(name, "").strip()
    return Path(raw) if raw else None


def hermes_root() -> Path:
    """The shared Hermes root, e.g. ``C:\\Users\\user\\AppData\\Local\\hermes``."""
    explicit = _env_path("HERMES_HOME")
    if explicit is not None:
        return explicit
    local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
    if local_appdata:
        return Path(local_appdata) / "hermes"
    return Path.home() / "AppData" / "Local" / "hermes"


def kanban_home() -> Path:
    """``<root>/kanban``, or the ``HERMES_KANBAN_HOME`` override.

    ``HERMES_KANBAN_HOME`` points at the *root* in Hermes' own resolution, so when it is
    set we append ``kanban`` the same way. The fixture dev mode relies on this.
    """
    override = _env_path("HERMES_KANBAN_HOME")
    base = override if override is not None else hermes_root()
    return base / "kanban"


def default_board_db() -> Path:
    """The pre-boards back-compat location: ``<root>/kanban.db``."""
    override = _env_path("HERMES_KANBAN_HOME")
    base = override if override is not None else hermes_root()
    return base / "kanban.db"


def boards_dir() -> Path:
    return kanban_home() / "boards"


def board_dir(slug: str) -> Path:
    return boards_dir() / slug


def board_db(slug: str) -> Path:
    if slug == "default":
        return default_board_db()
    return board_dir(slug) / "kanban.db"


def board_metadata(slug: str) -> Path:
    return board_dir(slug) / "board.json"


def current_board_pointer() -> Path:
    """One-line text file holding the active board slug."""
    return kanban_home() / "current"


def worker_logs_dir(slug: str) -> Path:
    if slug == "default":
        return kanban_home() / "logs"
    return board_dir(slug) / "logs"


def worker_log(slug: str, task_id: str) -> Path:
    return worker_logs_dir(slug) / f"{task_id}.log"


def pinned_board_db() -> Path | None:
    """``HERMES_KANBAN_DB`` pins one literal file, bypassing board resolution."""
    return _env_path("HERMES_KANBAN_DB")


def pinned_board_slug() -> str | None:
    raw = os.environ.get("HERMES_KANBAN_BOARD", "").strip()
    return raw or None


def is_denylisted(path: Path) -> bool:
    resolved = str(path.resolve()).casefold()
    return any(resolved == str(Path(d).resolve()).casefold() for d in DENYLISTED_DB_PATHS)
