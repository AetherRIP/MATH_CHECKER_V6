"""FastAPI application for Math Checker V6.

Phase 1 serves the static frontend and a very small JSON API. There is no
database, no background worker, and no AI client — the process is idle until
a request arrives. Future phases add API routers and the correction engine
behind the boundaries described in docs/architecture.md.
"""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import storage, system
from .config import APP_NAME, APP_VERSION, ensure_dirs, get_config

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"

log = logging.getLogger("mathchecker")


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = ensure_dirs()
    logging.basicConfig(
        level=getattr(logging, cfg.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log.info("%s %s ready (data dir configured)", APP_NAME, APP_VERSION)
    yield


app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    lifespan=lifespan,
    # The interactive docs UIs load assets from a CDN; the OpenAPI document
    # itself stays available at /api/openapi.json for future integrations.
    docs_url=None,
    redoc_url=None,
)

app.include_router(system.router)
app.include_router(storage.router)


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    """Never leak stack traces or paths to the client; log details server-side."""
    request_id = uuid.uuid4().hex[:12]
    log.exception("Unhandled error [%s] on %s %s", request_id, request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": "An unexpected error occurred.",
                "request_id": request_id,
            }
        },
    )


# Static frontend, mounted last so /api/* routes win. Starlette's StaticFiles
# resolves every request inside the directory (no traversal) and serves
# index.html for "/".
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
