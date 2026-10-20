"""FastAPI application for Math Checker V6.

Phase 2 added a local SQLite database behind a storage boundary; Phase 3 adds
the correction engine behind `app.engine`; Phase 4 adds durable correction
jobs, uploads and the result API. The process makes no provider call at
startup. Correction jobs run in a bounded daemon worker after the HTTP
request has created the durable queued record. If the database cannot
initialize, the application starts degraded — the UI and liveness probe still
work, and data routes return a safe 503 error envelope.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from .api import classroom, corrections, database, settings, storage, system
from .api.error_handlers import register_error_handlers
from .config import APP_NAME, APP_VERSION, ensure_dirs
from .correction.jobs import CorrectionJobService
from .db import Database, DatabaseError
from .engine import get_engine
from .logging_setup import (
    configure_logging,
    get_logger,
    new_request_id,
    set_request_id,
)
from .storage import Storage

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
ROUTINE_PATHS = frozenset({"/api/health", "/api/system/status"})

log = get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create the data directories, logging and database; never crash on failure."""
    configure_logging("INFO")
    app.state.storage = None
    app.state.jobs = None
    # Construct the engine once: its Phase 3 registry is per instance and a
    # provider call must never happen at startup. The honest unavailable
    # fallback is still a usable object for readiness/status.
    app.state.engine = get_engine()

    try:
        config = ensure_dirs()
        configure_logging(config.log_level)
        database = Database(config.database_path)
        database.initialize()
        storage_layer = Storage(database)
    except (DatabaseError, OSError, sqlite3.Error):
        # Startup failure is reported, not fatal: the UI and /api/health stay
        # available, and data routes answer with a safe 503 envelope.
        log.exception("database initialization failed")
    else:
        app.state.storage = storage_layer
        jobs = CorrectionJobService(
            storage_layer, app.state.engine, config.uploads_dir
        )
        try:
            jobs.recover_interrupted()
        except Exception:
            # Recovery is important but must not take the whole application
            # down; data routes still work and a later restart retries it.
            log.exception("interrupted correction-job recovery failed")
        app.state.jobs = jobs
        log.info("%s %s ready (database schema initialized)", APP_NAME, APP_VERSION)

    yield


app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    lifespan=lifespan,
    # The interactive docs UIs load assets from a CDN; the OpenAPI document
    # stays available for future integrations.
    docs_url=None,
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

register_error_handlers(app)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """Attach a request id to every request without logging request bodies."""
    request_id = new_request_id()
    request.state.request_id = request_id
    set_request_id(request_id)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        set_request_id(None)

    response.headers["X-Request-ID"] = request_id
    duration_ms = int((time.perf_counter() - started) * 1000)
    if response.status_code >= 500:
        level = logging.ERROR
    elif response.status_code >= 400:
        level = logging.WARNING
    elif request.url.path in ROUTINE_PATHS:
        level = logging.DEBUG
    else:
        level = logging.INFO
    log.log(
        level,
        "%s %s -> %s (%d ms) [%s]",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
        request_id,
    )
    return response


app.include_router(system.router)
app.include_router(settings.router)
app.include_router(database.router)
app.include_router(storage.router)
app.include_router(corrections.router)
app.include_router(classroom.router)


# Static frontend, mounted last so /api/* routes win. Starlette's StaticFiles
# resolves every request inside the directory (no traversal) and serves
# index.html for "/".
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
