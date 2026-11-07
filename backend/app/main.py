"""FastAPI application: serves /api and (once built) the frontend from /static."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import router
from app.config import settings
from app.service import seed_ahmed
from app.store import ProjectStore, get_store

_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def create_app(store: ProjectStore | None = None, *, seed_on_start: bool = True) -> FastAPI:
    """Build the app. Tests pass their own store; uvicorn uses the configured one."""
    active_store = store if store is not None else get_store()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Open the demo on real data: Ahmed's villa at month 8. Only written if missing.
        if seed_on_start:
            seed_ahmed(active_store)
        yield

    app = FastAPI(title="Bunyan API", version="0.1.0", lifespan=lifespan)
    app.state.store = active_store

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "firestore_disabled": settings.firestore_disabled,
            "gemini_mode": settings.gemini_mode,
        }

    app.include_router(router)

    if _DIST.is_dir():
        app.mount("/static", StaticFiles(directory=_DIST, html=True), name="static")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(_DIST / "index.html")

    return app


app = create_app()
