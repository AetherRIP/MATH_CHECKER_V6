"""Google Classroom integration API.

Routes stay thin and delegate to :mod:`app.classroom.service`. Only
necessary integration operations are exposed; no token, client-secret or
Drive content ever appears in a response.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..classroom import auth as classroom_auth
from ..classroom.client import ClassroomApiError
from ..classroom.service import ClassroomService
from ..config import classroom_configured
from ..db import CURRENT_SCHEMA_VERSION
from .deps import get_classroom_service
from .errors import ApiError

router = APIRouter(prefix="/api/classroom", tags=["classroom"])


class PublishGradeRequest(BaseModel):
    coursework_id: str
    submission_id: str
    job_id: str
    grade: float
    assigned: bool = True
    return_to_student: bool = False


class AttachReportRequest(BaseModel):
    coursework_id: str
    submission_id: str
    job_id: str
    filename: str | None = None


def _require_database_ready(service: ClassroomService) -> None:
    if CURRENT_SCHEMA_VERSION < 3:
        raise ApiError(503, "database_unavailable", "The local database is not available.")


@router.get("/status")
def classroom_status(service: ClassroomService = Depends(get_classroom_service)) -> dict:
    """Public readiness snapshot. Returns which prerequisite is missing."""
    state = service.auth_state()
    return {
        "configured": classroom_configured(),
        "connected": state["connected"],
        "email": state["email"],
        "problem": state["problem"],
        "publish_allowed": service.publish_allowed,
    }


@router.post("/connect")
def classroom_connect(
    open_browser: bool = True,
    service: ClassroomService = Depends(get_classroom_service),
) -> dict:
    """Run the interactive OAuth connect flow (loopback redirect)."""
    try:
        return service.connect(open_browser=open_browser)
    except classroom_auth.AuthError as exc:
        raise ApiError(400, "classroom_connect_failed", str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise ApiError(502, "classroom_connect_failed",
                       f"Classroom connection failed: {exc}") from exc


@router.post("/disconnect")
def classroom_disconnect(service: ClassroomService = Depends(get_classroom_service)) -> dict:
    return service.disconnect()


@router.get("/courses")
def classroom_courses(
    force: bool = False,
    service: ClassroomService = Depends(get_classroom_service),
) -> dict:
    _require_database_ready(service)
    try:
        courses = service.sync_courses(force=force)
    except classroom_auth.AuthError as exc:
        raise ApiError(401, "classroom_auth_required", str(exc)) from exc
    except ClassroomApiError as exc:
        raise ApiError(502, "classroom_api_error", str(exc)) from exc
    return {"courses": courses}


@router.get("/courses/{course_id}/coursework")
def classroom_coursework(
    course_id: str,
    force: bool = False,
    service: ClassroomService = Depends(get_classroom_service),
) -> dict:
    _require_database_ready(service)
    try:
        coursework = service.sync_coursework(course_id, force=force)
    except classroom_auth.AuthError as exc:
        raise ApiError(401, "classroom_auth_required", str(exc)) from exc
    except ClassroomApiError as exc:
        raise ApiError(502, "classroom_api_error", str(exc)) from exc
    return {"coursework": coursework}


@router.get("/courses/{course_id}/coursework/{coursework_id}/submissions")
def classroom_submissions(
    course_id: str,
    coursework_id: str,
    force: bool = False,
    service: ClassroomService = Depends(get_classroom_service),
) -> dict:
    _require_database_ready(service)
    try:
        submissions = service.sync_submissions(course_id, coursework_id, force=force)
    except classroom_auth.AuthError as exc:
        raise ApiError(401, "classroom_auth_required", str(exc)) from exc
    except ClassroomApiError as exc:
        raise ApiError(502, "classroom_api_error", str(exc)) from exc
    return {"submissions": submissions}


@router.get("/coursework/{coursework_id}/ops")
def classroom_publish_ops(
    coursework_id: str,
    service: ClassroomService = Depends(get_classroom_service),
) -> dict:
    return {"ops": service.storage.classroom_publish_ops(coursework_id)}
