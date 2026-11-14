"""LineZero API entry point:  uvicorn app.main:app"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.router import api_router
from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import register_exception_handlers
from app.core.migrations import run_migrations

logger = logging.getLogger("linezero")


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if settings.auto_migrate:
            run_migrations()
            logger.info("Database migrated: %s", settings.resolved_database_url)
        yield

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="LineZero backend: queue management, simulation, prediction, bottleneck detection, optimisation, analytics and reports.",
        debug=settings.debug,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)
    app.include_router(api_router)

    @app.get("/", tags=["meta"])
    def root():
        return {"name": settings.app_name, "version": settings.app_version, "docs": "/docs", "api": "/api/v1"}

    @app.get("/health", tags=["meta"])
    def health(db: Session = Depends(get_db)):
        try:
            db.execute(text("SELECT 1"))
        except Exception:
            return JSONResponse({"status": "degraded", "database": "unreachable"}, status_code=503)
        return {"status": "ok", "database": "ok", "version": settings.app_version}

    return app


app = create_app()
