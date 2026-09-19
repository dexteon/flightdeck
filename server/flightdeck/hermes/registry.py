"""Discovery of every Hermes board on disk.

The filesystem is authoritative. Hermes' ``GET /boards`` is merged in as advisory only
when the dashboard happens to be up, so the registry is fully functional with Hermes down.

A board that fails validation is kept in the registry marked ``unavailable`` with a
reason, never dropped. That is deliberate: the fleet view must be able to say
"13 of 14 reporting" rather than silently showing a shorter list.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from . import paths
from .readdb import BoardUnavailable, readers

log = logging.getLogger(__name__)

BoardState = Literal["available", "unavailable"]


@dataclass(slots=True)
class Board:
    slug: str
    db_path: Path
    state: BoardState = "available"
    reason: str | None = None
    name: str | None = None
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    default_workdir: str | None = None
    project_id: str | None = None
    created_at: int | None = None
    archived: bool = False
    is_current: bool = False
    schema_fingerprint: str | None = None

    @property
    def display_name(self) -> str:
        return self.name or self.slug

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "state": self.state,
            "reason": self.reason,
            "name": self.display_name,
            "description": self.description,
            "icon": self.icon,
            "color": self.color,
            "default_workdir": self.default_workdir,
            "project_id": self.project_id,
            "created_at": self.created_at,
            "archived": self.archived,
            "is_current": self.is_current,
            "schema_fingerprint": self.schema_fingerprint,
        }


def _read_board_json(slug: str) -> dict[str, Any]:
    """Parse ``board.json``. A missing or malformed file degrades, never raises."""
    path = paths.board_metadata(slug)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("board.json unreadable for %s: %s", slug, exc)
        return {}
    return raw if isinstance(raw, dict) else {}


def _read_current_slug() -> str | None:
    pinned = paths.pinned_board_slug()
    if pinned:
        return pinned
    try:
        value = paths.current_board_pointer().read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def _validate(slug: str, db_path: Path) -> tuple[BoardState, str | None, str | None]:
    """Open read-only and confirm a ``tasks`` table exists.

    Returns ``(state, reason, schema_fingerprint)``.
    """
    if paths.is_denylisted(db_path):
        return "unavailable", "denylisted path (known-dead database)", None
    try:
        size = db_path.stat().st_size
    except OSError as exc:
        return "unavailable", f"stat failed: {exc}", None
    if size == 0:
        return "unavailable", "database file is 0 bytes", None
    try:
        reader = readers.get(slug, db_path)
        schema = reader.schema()
    except BoardUnavailable as exc:
        return "unavailable", exc.reason, None
    except Exception as exc:  # pragma: no cover - defensive
        return "unavailable", f"{type(exc).__name__}: {exc}", None
    if not schema.has_table("tasks"):
        return "unavailable", "no tasks table (not a kanban database)", None
    return "available", None, schema.fingerprint


@dataclass(slots=True)
class _ScanStamp:
    boards_mtime: float | None = None
    current_mtime: float | None = None


class BoardRegistry:
    """In-memory map of slug to :class:`Board`, refreshed by a cheap stat check."""

    def __init__(self) -> None:
        self._boards: dict[str, Board] = {}
        self._stamp = _ScanStamp()
        self._advisory: dict[str, dict[str, Any]] = {}

    # -- access ---------------------------------------------------------------

    def all(self, *, include_archived: bool = True) -> list[Board]:
        out = [b for b in self._boards.values() if include_archived or not b.archived]
        return sorted(out, key=lambda b: (b.slug != "default", b.slug.casefold()))

    def available(self) -> list[Board]:
        return [b for b in self.all() if b.state == "available"]

    def get(self, slug: str) -> Board | None:
        return self._boards.get(slug)

    def require(self, slug: str) -> Board:
        board = self._boards.get(slug)
        if board is None:
            raise BoardUnavailable(slug, "unknown board")
        if board.state != "available":
            raise BoardUnavailable(slug, board.reason or "unavailable")
        return board

    def summary(self) -> dict[str, Any]:
        boards = self.all()
        unavailable = [
            {"slug": b.slug, "reason": b.reason} for b in boards if b.state != "available"
        ]
        return {
            "total": len(boards),
            "available": len(boards) - len(unavailable),
            "unavailable": unavailable,
        }

    def fingerprints(self) -> dict[str, str]:
        return {
            b.slug: b.schema_fingerprint
            for b in self._boards.values()
            if b.schema_fingerprint
        }

    # -- scanning -------------------------------------------------------------

    def _candidate_paths(self) -> dict[str, Path]:
        pinned_db = paths.pinned_board_db()
        if pinned_db is not None:
            slug = paths.pinned_board_slug() or "default"
            return {slug: pinned_db}

        found: dict[str, Path] = {"default": paths.default_board_db()}
        boards_root = paths.boards_dir()
        try:
            entries = sorted(p for p in boards_root.iterdir() if p.is_dir())
        except OSError:
            entries = []
        for entry in entries:
            if entry.name.startswith("_"):
                # `_archived/` holds removed boards, not live ones.
                continue
            db = entry / "kanban.db"
            if db.exists():
                found[entry.name] = db
        return found

    def scan(self, *, force: bool = False) -> bool:
        """Rescan if anything changed. Returns True when the registry was rebuilt."""
        if not force and not self._changed_on_disk():
            return False

        current = _read_current_slug()
        rebuilt: dict[str, Board] = {}
        for slug, db_path in self._candidate_paths().items():
            state, reason, fingerprint = _validate(slug, db_path)
            meta = _read_board_json(slug) if slug != "default" else {}
            rebuilt[slug] = Board(
                slug=slug,
                db_path=db_path,
                state=state,
                reason=reason,
                # `board.json` carries its own slug but the directory name is what
                # Hermes trusts, so we never read `slug` back out of the file.
                name=meta.get("name") or ("default" if slug == "default" else None),
                description=meta.get("description"),
                icon=meta.get("icon") or None,
                color=meta.get("color") or None,
                default_workdir=meta.get("default_workdir"),
                project_id=meta.get("project_id"),
                created_at=meta.get("created_at"),
                archived=bool(meta.get("archived", False)),
                is_current=(slug == current) or (current is None and slug == "default"),
                schema_fingerprint=fingerprint,
            )

        self._apply_advisory(rebuilt)

        for slug in set(self._boards) - set(rebuilt):
            readers.drop(slug)
        self._boards = rebuilt
        return True

    def _changed_on_disk(self) -> bool:
        if not self._boards:
            return True

        def mtime(path: Path) -> float | None:
            try:
                return path.stat().st_mtime
            except OSError:
                return None

        boards_mtime = mtime(paths.boards_dir())
        current_mtime = mtime(paths.current_board_pointer())
        if (
            boards_mtime == self._stamp.boards_mtime
            and current_mtime == self._stamp.current_mtime
        ):
            return False
        self._stamp = _ScanStamp(boards_mtime, current_mtime)
        return True

    # -- advisory merge from the Hermes API -----------------------------------

    def set_advisory(self, api_boards: list[dict[str, Any]]) -> None:
        """Record ``GET /boards`` output. Advisory only; the filesystem still wins.

        This catches a board created through the API whose database file has not
        materialized yet, and picks up authoritative ``archived`` flags.
        """
        self._advisory = {b["slug"]: b for b in api_boards if b.get("slug")}
        if self._boards:
            self._apply_advisory(self._boards)

    def _apply_advisory(self, boards: dict[str, Board]) -> None:
        for slug, api in self._advisory.items():
            board = boards.get(slug)
            if board is None:
                boards[slug] = Board(
                    slug=slug,
                    db_path=paths.board_db(slug),
                    state="unavailable",
                    reason="known to Hermes, no database file on disk yet",
                    name=api.get("name"),
                    description=api.get("description"),
                    project_id=api.get("project_id"),
                )
                continue
            if board.name is None and api.get("name"):
                board.name = api["name"]
            if api.get("archived") is not None:
                board.archived = bool(api["archived"])


registry = BoardRegistry()
