"""Flightdeck application factory.

One process, one port. In production the same FastAPI app serves the built SPA out of
``web/dist``; the Vite dev server on 9311 exists only while developing.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import routes_fleet, routes_health, routes_stream, routes_tasks
from .api.deps import lifespan_state
from .config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("flightdeck")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with lifespan_state() as state:
        app.state.flightdeck = state
        log.info(
            "flightdeck up on http://%s:%s (hermes at %s)",
            settings.host,
            settings.port,
            settings.hermes_url,
        )
        yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Flightdeck",
        description="Cross-board fleet command center for the Hermes Agent kanban",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    app.include_router(routes_health.router, prefix="/api")
    app.include_router(routes_fleet.router, prefix="/api")
    app.include_router(routes_tasks.router, prefix="/api")
    # The websocket is not under /api: it is the transport, not a resource.
    app.include_router(routes_stream.router)

    dist = settings.web_dist
    if dist.is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        index = dist / "index.html"

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str) -> FileResponse:
            """Serve the built file when there is one, else the shell.

            Client-side routes like /fleet and /b/<slug>/t/<id> have no file behind
            them, so a bare StaticFiles mount 404s them on refresh or on a shared link.
            """
            candidate = (dist / full_path).resolve()
            if full_path and candidate.is_file() and candidate.is_relative_to(dist.resolve()):
                return FileResponse(candidate)
            return FileResponse(index)
    else:
        log.warning("web/dist not built; serving API only")

    return app


app = create_app()
