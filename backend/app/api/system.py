"""System endpoints: liveness and readiness.

``/api/health`` is a liveness probe only: the process is serving requests.
``/api/system/status`` reports real readiness, including whether the local
database initialized. Responses contain explicit flags and version strings —
never secrets, credentials or server filesystem paths.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..config import (
    APP_NAME,
    APP_PHASE,
    APP_VERSION,
    ai_provider_configured,
    classroom_configured,
)
from ..db import DATABASE_UNAVAILABLE_DETAIL
from ..engine import get_engine
from ..models import DatabaseStatus

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health() -> dict:
    """Liveness probe: the server is up and serving requests."""
    return {"status": "ok"}


@router.get("/system/status")
def system_status(request: Request) -> dict:
    """Readiness summary: version, database state and honest feature flags."""
    storage = getattr(request.app.state, "storage", None)
    if storage is None:
        database = DatabaseStatus(
            ready=False,
            detail=DATABASE_UNAVAILABLE_DETAIL,
        )
    else:
        database = storage.database_status()

    engine_info = get_engine().describe()

    return {
        "app_name": APP_NAME,
        "version": APP_VERSION,
        "phase": APP_PHASE,
        "ai_provider_configured": ai_provider_configured(),
        "classroom_configured": classroom_configured(),
        "correction_engine": {
            "name": engine_info.name,
            "available": engine_info.available,
            "reason": engine_info.reason,
        },
        "database": {
            "status": "ready" if database.ready else "unavailable",
            "schema_version": database.schema_version,
            "detail": database.detail,
        },
        "features": {
            "file_selection": True,
            "ui_preferences": True,
            "storage_overview": True,
            "database": True,
            "settings": True,
            # The engine capability is reported from the live engine, not from
            # a hard-coded promise: no provider key means no correction.
            "ai_correction": engine_info.available,
            "pdf_processing": True,
            "grade_submission": engine_info.available,
            "reports": False,
            "classroom_sync": False,
            "background_tasks": False,
        },
    }
