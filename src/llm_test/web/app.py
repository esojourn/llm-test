"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    from .database import init_db
    await init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="llm-test", docs_url=None, redoc_url=None, lifespan=lifespan)

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    from .routes import auth, pages, api
    app.include_router(pages.router)
    app.include_router(auth.router, prefix="/api/auth")
    app.include_router(api.router, prefix="/api")

    return app


app = create_app()
