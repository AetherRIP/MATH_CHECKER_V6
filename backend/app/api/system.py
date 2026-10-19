"""System endpoints: liveness and readiness.

These are among the only API calls the Phase 1 UI makes. Responses contain
explicit booleans and version strings only — never secrets, credentials, or
server filesystem paths.
"""

from __future__ import annotations

from fastapi import APIRouter

from ..config import (
    APP_NAME,
    APP_PHASE,
    APP_VERSION,
    ai_provider_configured,
    classroom_configured,
)

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health() -> dict:
    """Liveness probe: the server is up and serving requests."""
    return {"status": "ok"}


@router.get("/system/status")
def system_status() -> dict:
    """Readiness summary: version and honest feature availability.

    ``*_configured`` flags reflect real state (whether the corresponding
    environment configuration exists). Feature flags describe what this
    phase actually implements — nothing is claimed as working before it is.
    """
    return {
        "app_name": APP_NAME,
        "version": APP_VERSION,
        "phase": APP_PHASE,
        "ai_provider_configured": ai_provider_configured(),
        "classroom_configured": classroom_configured(),
        "features": {
            "file_selection": True,
            "ui_preferences": True,
            "storage_overview": True,
            "ai_correction": False,
            "pdf_processing": False,
            "grade_submission": False,
            "reports": False,
            "classroom_sync": False,
            "background_tasks": False,
        },
    }
