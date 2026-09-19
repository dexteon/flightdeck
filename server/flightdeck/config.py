"""Runtime settings.

Everything Flightdeck needs to find Hermes, plus the knobs the plan calls out as
configurable. Values come from the environment (prefix ``FLIGHTDECK_``) or an ``.env``
file; the Hermes-side variables keep their native names because they are Hermes' own
contract and the fixture dev mode sets them directly.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FLIGHTDECK_",
        env_file=".env",
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 9310

    # Hermes dashboard base URL. Writes proxy here; reads never touch it.
    hermes_url: str = "http://127.0.0.1:9119"

    # Health probe cadence and the consecutive-failure count that declares DOWN.
    # Two failures debounces an ordinary dashboard restart.
    health_probe_seconds: float = 5.0
    health_down_after_failures: int = 2

    # A task whose last heartbeat is older than this is shown as stale.
    # Hermes hardcodes 120s; we expose it.
    stale_heartbeat_seconds: int = 120

    # Board registry rescan cadence. Cheap: stat() first, full scan only on mtime change.
    registry_rescan_seconds: float = 10.0

    # Read-only connection pool, per board.
    pool_max_per_board: int = 4
    pool_idle_evict_seconds: float = 120.0
    sqlite_busy_timeout_ms: int = 5000

    # Transient IOERR budget, mirroring hermes_state.py:162-169 exactly.
    read_retry_attempts: int = 3
    read_retry_backoff_seconds: float = 0.05

    @property
    def repo_root(self) -> Path:
        # config.py -> flightdeck -> server -> repo root
        return Path(__file__).resolve().parents[2]

    @property
    def var_dir(self) -> Path:
        return self.repo_root / "var"

    @property
    def web_dist(self) -> Path:
        return self.repo_root / "web" / "dist"


settings = Settings()
