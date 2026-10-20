"""Correction-job HTTP surface (Phase 4).

Routes stay thin: multipart parsing, safe error mapping and JSON shape live
here; validation, workspace ownership, lifecycle transitions and persistence
belong to :class:`app.correction.jobs.CorrectionJobService`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Header, Query, UploadFile

from ..correction.jobs import (
    CorrectionJobService,
    IncomingUpload,
    JobEngineUnavailable,
    JobInputError,
    JobNotFound,
    ReportNotReady,
)
from ..engine import (
    CorrectionReport,
    MarkedItem,
    REPORT_COMPLETED,
)
from ..models import CorrectionJobRecord
from .deps import get_job_service
from .errors import ApiError

router = APIRouter(prefix="/api/corrections", tags=["corrections"])

_ROLE_ORDER = {"submission": 0, "mark_scheme": 1}


def job_payload(record: CorrectionJobRecord) -> dict:
    """The wire shape of a job. Server paths and mark-scheme text stay out."""
    files = sorted(
        record.files,
        key=lambda file: (_ROLE_ORDER.get(file.role, 9), file.position),
    )
    return {
        "job_id": record.job_id,
        "status": record.status.value,
        "assignment_title": record.assignment_title,
        "created_at": record.created_at,
        "started_at": record.started_at,
        "completed_at": record.completed_at,
        "files": [
            {
                "role": file.role,
                "filename": file.filename,
                "media_type": file.media_type,
                "size_bytes": file.size_bytes,
            }
            for file in files
        ],
        "report_status": record.report_status,
        "awarded": record.awarded,
        "out_of": record.out_of,
        "percentage": record.percentage,
        "review_required": record.review_required,
        "warnings": list(record.warnings),
        "error": record.error,
        "engine": record.engine,
    }


def item_payload(item: MarkedItem) -> dict:
    return {
        "label": item.label,
        "awarded": item.awarded,
        "out_of": item.out_of,
        "feedback": item.feedback,
        "criteria": list(item.criteria),
        "student_evidence": item.student_evidence,
        "scheme_evidence": item.scheme_evidence,
        "verification": item.verification,
        "student_answer": item.student_answer,
        "scheme_answer": item.scheme_answer,
        "status": item.status,
        "warnings": list(item.warnings),
        "review_flags": list(item.review_flags),
    }


def report_payload(report: CorrectionReport) -> dict:
    return {
        "job_id": report.job_id,
        "summary": report.summary,
        "awarded": report.awarded,
        "out_of": report.out_of,
        "percentage": report.percentage,
        "status": report.status,
        "review_required": report.review_required,
        "unresolved": list(report.unresolved),
        "warnings": list(report.warnings),
        "engine": report.engine,
        "created_at": report.created_at,
        "items": [item_payload(item) for item in report.items],
    }


def _uploads(files: list[UploadFile] | None) -> list[IncomingUpload]:
    return [
        IncomingUpload(
            filename=upload.filename or "",
            media_type=upload.content_type,
            stream=upload.file,
        )
        for upload in (files or [])
        if upload.filename
    ]


@router.post("", status_code=202)
def create_correction(
    files: list[UploadFile] = File(...),
    mark_scheme_files: list[UploadFile] | None = File(None),
    assignment_title: str = Form(...),
    instructions: str = Form(""),
    mark_scheme: str = Form(""),
    feedback_detail: str = Form("detailed"),
    max_score: str | None = Form(None),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    service: CorrectionJobService = Depends(get_job_service),
) -> dict:
    """Validate uploads, create a durable queued job and return it."""
    try:
        record = service.create_job(
            assignment_title=assignment_title,
            instructions=instructions,
            mark_scheme_text=mark_scheme,
            feedback_detail=feedback_detail,
            max_score=max_score,
            submission_uploads=_uploads(files),
            scheme_uploads=_uploads(mark_scheme_files),
            idempotency_key=idempotency_key,
        )
    except JobEngineUnavailable as exc:
        raise ApiError(503, "engine_unavailable", str(exc)) from exc
    except JobInputError as exc:
        raise ApiError(422, "unsupported_input", str(exc)) from exc
    return job_payload(record)


@router.get("")
def list_corrections(
    limit: int = Query(50, ge=1, le=200),
    service: CorrectionJobService = Depends(get_job_service),
) -> dict:
    jobs = service.list_jobs(limit=limit)
    return {"jobs": [job_payload(job) for job in jobs]}


@router.get("/{job_id}")
def get_correction(
    job_id: str,
    service: CorrectionJobService = Depends(get_job_service),
) -> dict:
    try:
        return job_payload(service.get_job(job_id))
    except JobNotFound as exc:
        raise ApiError(404, "job_not_found", str(exc)) from exc


@router.get("/{job_id}/report")
def get_correction_report(
    job_id: str,
    service: CorrectionJobService = Depends(get_job_service),
) -> dict:
    try:
        report = service.get_report(job_id)
    except JobNotFound as exc:
        raise ApiError(404, "job_not_found", str(exc)) from exc
    except ReportNotReady as exc:
        raise ApiError(409, "report_not_ready", str(exc)) from exc
    return report_payload(report)


# Kept explicit so an accidental status rename in the engine is caught here.
if REPORT_COMPLETED != "completed":  # pragma: no cover - contract guard
    raise RuntimeError("The engine's completed report status changed.")
