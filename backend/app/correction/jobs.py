"""Phase 4 orchestration: uploaded files → durable job → Phase 3 engine.

This service is the application boundary around the correction engine. It owns
the pieces Phase 3 deliberately left out:

* a per-job upload workspace, created before the job row and removed when the
  job reaches a terminal state (including every failure path);
* the durable ``queued → processing → completed | failed`` lifecycle;
* one writer per job, bounded to a small number of concurrent provider calls;
* persistence of the validated report before the job is marked completed;
* idempotent submission keys so a retried request cannot create duplicates;
* startup reconciliation of jobs interrupted by a restart.

The engine remains independent: it is injected through the Phase 3
``CorrectionEngine`` protocol, receives ``SubmissionFile`` paths, and owns all
marking rules. This module never calls the provider or inspects a document's
marks itself.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable, Sequence

from ..engine import (
    ACCEPTED_MEDIA_TYPES,
    MAX_FILES,
    AssignmentContext,
    CorrectionEngine,
    CorrectionOptions,
    CorrectionReport,
    CorrectionRequest,
    EngineError,
    EngineUnavailableError,
    ExtractionError,
    JobStatus,
    SubmissionFile,
    UnsupportedInputError,
    validate_request,
)
from ..models import CorrectionJobFile, CorrectionJobRecord, new_id, utc_now
from ..storage import ConflictError, NotFoundError, Storage, StorageError
from .documents import extract_document

log = logging.getLogger("mathchecker.correction.jobs")

MAX_STORED_FILENAME = 255
MAX_IDEMPOTENCY_KEY = 128
JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")

GENERIC_FAILURE = "The correction engine failed unexpectedly. The job was not completed."
INTERRUPTED_FAILURE = (
    "Processing was interrupted by an application restart. Submit the files again."
)
STORAGE_FAILURE = "The correction results could not be saved. The job was not completed."


class JobServiceError(Exception):
    """Base class for safe, user-facing job-service failures."""


class JobInputError(JobServiceError):
    """An upload or job request is invalid."""


class JobEngineUnavailable(JobServiceError):
    """No configured engine can run corrections."""


class JobNotFound(JobServiceError):
    """The requested durable job does not exist."""


class ReportNotReady(JobServiceError):
    """The job has no completed report to return."""


class JobConflict(JobServiceError):
    """The job is in a state that does not allow the requested operation."""


@dataclass(frozen=True)
class IncomingUpload:
    """A file handed to the job service by the HTTP layer.

    ``stream`` is a binary file-like object positioned at the start. The
    service reads it once into the job workspace; the API never guesses a
    size or trusts the browser's content type without checking the bytes.
    """

    filename: str
    media_type: str | None
    stream: BinaryIO


class CorrectionJobService:
    """Durable, bounded correction-job runner."""

    def __init__(
        self,
        storage: Storage,
        engine: CorrectionEngine,
        uploads_root: Path | str,
        *,
        clock: Callable[[], str] = utc_now,
        max_workers: int = 2,
        max_file_bytes: int | None = None,
        extract: Callable[[SubmissionFile, str], object] = extract_document,
    ):
        self._storage = storage
        self._engine = engine
        self._root = Path(uploads_root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._max_file_bytes = max_file_bytes
        self._extract = extract
        self._slots = threading.BoundedSemaphore(max(1, int(max_workers)))

    # --- public API ------------------------------------------------------

    def describe(self):
        return self._engine.describe()

    @property
    def available(self) -> bool:
        return bool(self._engine.describe().available)

    def create_job(
        self,
        *,
        assignment_title: str,
        instructions: str = "",
        mark_scheme_text: str = "",
        feedback_detail: str = "detailed",
        max_score: float | None = None,
        partial_credit: bool = True,
        submission_uploads: Sequence[IncomingUpload],
        scheme_uploads: Sequence[IncomingUpload] = (),
        idempotency_key: str | None = None,
    ) -> CorrectionJobRecord:
        """Validate and store one queued job, then start its worker.

        Invalid input is rejected before a job row exists. A repeated
        idempotency key returns the existing job without writing another
        workspace or calling the engine again.
        """
        info = self._engine.describe()
        if not info.available:
            raise JobEngineUnavailable(info.reason or "Correction is unavailable.")

        title = _required_text(assignment_title, "Assignment title")
        instructions_text = _text(instructions)
        scheme_text = _text(mark_scheme_text)
        detail = _feedback_detail(feedback_detail)
        expected_total = _optional_positive_number(max_score)
        key = _idempotency_key(idempotency_key)

        if key:
            existing = self._storage.get_correction_job_by_idempotency(key)
            if existing is not None:
                return existing

        if not submission_uploads:
            raise JobInputError("Attach at least one student submission file.")
        total_files = len(submission_uploads) + len(scheme_uploads)
        if total_files > MAX_FILES:
            raise JobInputError(f"Attach at most {MAX_FILES} files.")
        if not scheme_uploads and not scheme_text.strip():
            raise JobInputError("Attach the mark scheme or paste its text.")
        limit = self._max_file_bytes or self._upload_limit_bytes()

        job_id = new_id()
        workspace = self._workspace(job_id)
        workspace.mkdir(parents=True, exist_ok=False)
        job_files: list[CorrectionJobFile] = []
        submission_files: list[SubmissionFile] = []
        scheme_files: list[SubmissionFile] = []

        try:
            for role, uploads, bucket in (
                ("submission", submission_uploads, submission_files),
                ("mark_scheme", scheme_uploads, scheme_files),
            ):
                for position, upload in enumerate(uploads):
                    filename = _clean_filename(upload.filename)
                    media_type = _media_type(filename, upload.media_type)
                    path = workspace / _stored_name(
                        role, position, _suffix_for(media_type)
                    )
                    size_bytes = self._save_upload(
                        upload.stream, path, limit, filename
                    )
                    item = SubmissionFile(
                        path=path,
                        filename=filename,
                        media_type=media_type,
                        size_bytes=size_bytes,
                    )
                    # Validate the actual bytes before creating a job. This
                    # uses the same Phase 3 extractor as the engine, so a
                    # corrupt/encrypted/mislabelled file is rejected at the
                    # boundary rather than after the job is queued.
                    try:
                        self._extract(item, role)
                    except ExtractionError as exc:
                        raise JobInputError(str(exc)) from exc
                    bucket.append(item)
                    job_files.append(
                        CorrectionJobFile(
                            role=role,
                            position=position,
                            filename=filename,
                            media_type=media_type,
                            size_bytes=size_bytes,
                        )
                    )

            request = CorrectionRequest(
                files=tuple(submission_files),
                assignment=AssignmentContext(
                    title=title,
                    instructions=instructions_text,
                    mark_scheme=scheme_text,
                ),
                options=CorrectionOptions(
                    partial_credit=partial_credit,
                    max_score=expected_total,
                    feedback_detail=detail,
                ),
                mark_scheme_files=tuple(scheme_files),
                job_id=job_id,
            )
            try:
                validate_request(request)
            except UnsupportedInputError as exc:
                raise JobInputError(str(exc)) from exc

            try:
                record = self._storage.create_correction_job(
                    job_id=job_id,
                    assignment_title=title,
                    instructions=instructions_text,
                    mark_scheme_text=scheme_text,
                    feedback_detail=detail,
                    max_score=expected_total,
                    partial_credit=partial_credit,
                    files=job_files,
                    idempotency_key=key,
                    created_at=self._clock(),
                )
            except ConflictError:
                # A concurrent request with the same key won the race. Use the
                # existing job; this workspace and its files are discarded.
                if key:
                    existing = self._storage.get_correction_job_by_idempotency(key)
                    if existing is not None:
                        self._cleanup_workspace(job_id)
                        return existing
                raise
        except Exception:
            self._cleanup_workspace(job_id)
            raise

        self._start_worker(job_id)
        return record

    def list_jobs(self, *, limit: int = 50) -> list[CorrectionJobRecord]:
        return self._storage.list_correction_jobs(limit=limit)

    def get_job(self, job_id: str) -> CorrectionJobRecord:
        record = self._storage.get_correction_job(job_id)
        if record is None:
            raise JobNotFound("The requested correction job was not found.")
        return record

    def get_report(self, job_id: str) -> CorrectionReport:
        record = self.get_job(job_id)
        if record.status is not JobStatus.COMPLETED:
            raise ReportNotReady(
                "The correction has not completed, so no result is available."
            )
        report = self._storage.get_correction_report(job_id)
        if report is None:
            raise ReportNotReady(
                "The correction has no stored report. The job was not completed."
            )
        return report

    def recover_interrupted(self) -> int:
        """Fail jobs left active by a previous process and clean workspaces.

        Completed and failed jobs are untouched. Their reports and error
        messages remain retrievable after a restart.
        """
        job_ids = self._storage.recover_interrupted_correction_jobs(INTERRUPTED_FAILURE)
        for job_id in job_ids:
            self._cleanup_workspace(job_id)
        self.prune_workspaces()
        if job_ids:
            log.warning("recovered %d interrupted correction job(s)", len(job_ids))
        return len(job_ids)

    def prune_workspaces(self) -> int:
        """Remove workspaces belonging to missing or terminal jobs."""
        removed = 0
        try:
            children = [child for child in self._root.iterdir() if child.is_dir()]
        except OSError:
            return 0
        for child in children:
            if not JOB_ID_RE.fullmatch(child.name):
                continue
            record = self._storage.get_correction_job(child.name)
            if record is None or record.status in (
                JobStatus.COMPLETED,
                JobStatus.FAILED,
            ):
                if self._cleanup_workspace(child.name):
                    removed += 1
        return removed

    def wait_for_terminal(self, job_id: str, *, timeout: float = 10.0) -> CorrectionJobRecord:
        """Poll the durable state until a terminal status (tests/tools only)."""
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            record = self.get_job(job_id)
            if record.status in (JobStatus.COMPLETED, JobStatus.FAILED):
                return record
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Correction job {job_id} did not finish in time.")
            time.sleep(0.02)

    # --- worker ----------------------------------------------------------

    def _start_worker(self, job_id: str) -> None:
        thread = threading.Thread(
            target=self._run_job,
            args=(job_id,),
            name=f"mc6-correction-{job_id[:8]}",
            daemon=True,
        )
        thread.start()

    def _run_job(self, job_id: str) -> None:
        started = time.perf_counter()
        try:
            with self._slots:
                try:
                    record = self._storage.mark_correction_job_processing(job_id)
                except (NotFoundError, ConflictError):
                    return
                try:
                    engine_job = asyncio.run(
                        self._engine.submit(self._request_for(record))
                    )
                    if engine_job.status is JobStatus.FAILED:
                        self._fail_safely(
                            job_id, engine_job.error or GENERIC_FAILURE
                        )
                        log.warning(
                            "correction job %s failed (%s)",
                            job_id,
                            type(engine_job).__name__,
                        )
                        return
                    report = asyncio.run(
                        self._engine.get_report(engine_job.job_id)
                    )
                    self._storage.complete_correction_job(job_id, report)
                    log.info(
                        "correction job %s completed in %.1fs (%d questions)",
                        job_id,
                        time.perf_counter() - started,
                        len(report.items),
                    )
                except EngineUnavailableError as exc:
                    self._fail_safely(job_id, str(exc) or GENERIC_FAILURE)
                except EngineError as exc:
                    self._fail_safely(job_id, str(exc) or GENERIC_FAILURE)
                except (StorageError, sqlite3.Error) as exc:
                    log.exception(
                        "correction job %s could not persist its report (%s)",
                        job_id,
                        type(exc).__name__,
                    )
                    self._fail_safely(job_id, STORAGE_FAILURE)
                except Exception:
                    log.exception("correction job %s crashed", job_id)
                    self._fail_safely(job_id, GENERIC_FAILURE)
                finally:
                    self._cleanup_workspace(job_id)
        except Exception:  # pragma: no cover - thread boundary safety
            log.exception("correction worker %s stopped unexpectedly", job_id)
            self._cleanup_workspace(job_id)

    def _request_for(self, record: CorrectionJobRecord) -> CorrectionRequest:
        submission_files = tuple(
            SubmissionFile(
                path=self._workspace(record.job_id)
                / _stored_name(
                    file.role, file.position, _suffix_for(file.media_type)
                ),
                filename=file.filename,
                media_type=file.media_type,
                size_bytes=file.size_bytes,
            )
            for file in record.files
            if file.role == "submission"
        )
        scheme_files = tuple(
            SubmissionFile(
                path=self._workspace(record.job_id)
                / _stored_name(
                    file.role, file.position, _suffix_for(file.media_type)
                ),
                filename=file.filename,
                media_type=file.media_type,
                size_bytes=file.size_bytes,
            )
            for file in record.files
            if file.role == "mark_scheme"
        )
        return CorrectionRequest(
            files=submission_files,
            assignment=AssignmentContext(
                title=record.assignment_title,
                instructions=record.instructions,
                mark_scheme=record.mark_scheme_text,
            ),
            options=CorrectionOptions(
                partial_credit=record.partial_credit,
                max_score=record.max_score,
                feedback_detail=record.feedback_detail,
            ),
            mark_scheme_files=scheme_files,
            job_id=record.job_id,
        )

    # --- workspace -------------------------------------------------------

    def _workspace(self, job_id: str) -> Path:
        if not JOB_ID_RE.fullmatch(str(job_id)):
            raise JobInputError("The correction job identifier is invalid.")
        root = self._root.resolve()
        workspace = (self._root / job_id).resolve()
        if workspace.parent != root:
            raise JobInputError("The correction workspace is invalid.")
        return workspace

    def _cleanup_workspace(self, job_id: str) -> bool:
        try:
            workspace = self._workspace(job_id)
        except JobInputError:
            return False
        try:
            shutil.rmtree(workspace)
            return True
        except FileNotFoundError:
            return False
        except OSError:
            log.warning("could not remove correction workspace for %s", job_id)
            return False

    def _save_upload(
        self,
        stream: BinaryIO,
        path: Path,
        limit: int,
        display_name: str,
    ) -> int:
        try:
            stream.seek(0)
        except (AttributeError, OSError):
            pass
        size = 0
        try:
            with path.open("wb") as handle:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > limit:
                        raise JobInputError(
                            f"'{display_name}' is larger than the configured upload limit."
                        )
                    handle.write(chunk)
        except OSError as exc:
            raise JobInputError("The uploaded file could not be stored.") from exc
        if size <= 0:
            raise JobInputError(f"'{display_name}' is empty.")
        return size

    def _upload_limit_bytes(self) -> int:
        try:
            settings = self._storage.get_settings()
            megabytes = int(settings.get("max_upload_mb", 25))
        except (StorageError, ValueError, TypeError):
            megabytes = 25
        return max(1, megabytes) * 1024 * 1024

    def _fail_safely(self, job_id: str, message: str) -> None:
        try:
            self._storage.fail_correction_job(job_id, message)
        except Exception:
            # If even the failure write cannot be persisted, leave the job as
            # processing; startup reconciliation will fail it honestly.
            log.exception("could not record failure for correction job %s", job_id)


def _stored_name(role: str, position: int, suffix: str) -> str:
    return f"{role}-{position}{suffix}"


def _suffix_for(media_type: str) -> str:
    return {
        "application/pdf": ".pdf",
        "image/png": ".png",
        "image/jpeg": ".jpg",
    }[media_type]


def _media_type(filename: str, supplied: str | None) -> str:
    value = (supplied or "").split(";", 1)[0].strip().lower()
    if value in ACCEPTED_MEDIA_TYPES:
        return value
    suffix = Path(filename).suffix.lower()
    inferred = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }.get(suffix)
    if inferred is None:
        raise JobInputError(
            f"'{filename}' is not a supported file type. Use PDF, PNG or JPEG."
        )
    return inferred


def _clean_filename(value: str | None) -> str:
    name = Path(str(value or "")).name.strip()
    if not name or name in (".", ".."):
        raise JobInputError("Every uploaded file needs a filename.")
    if len(name) > MAX_STORED_FILENAME:
        raise JobInputError("An uploaded filename is too long.")
    return name


def _required_text(value: str, label: str) -> str:
    text = _text(value)
    if not text:
        raise JobInputError(f"{label} is required.")
    return text


def _text(value: str | None) -> str:
    return str(value or "").strip()


def _feedback_detail(value: str) -> str:
    if value not in ("brief", "detailed"):
        raise JobInputError("Feedback detail must be 'brief' or 'detailed'.")
    return value


def _optional_positive_number(value: float | str | None) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise JobInputError("The expected total mark must be a number.") from exc
    if number <= 0 or number != number or number in (float("inf"), float("-inf")):
        raise JobInputError("The expected total mark must be a positive number.")
    return number


def _idempotency_key(value: str | None) -> str | None:
    key = (value or "").strip()
    if not key:
        return None
    if not _IDEMPOTENCY_RE.fullmatch(key):
        raise JobInputError(
            "Idempotency-Key must be 8–128 characters (letters, digits, . _ : -)."
        )
    return key


__all__ = [
    "CorrectionJobService",
    "IncomingUpload",
    "JobServiceError",
    "JobInputError",
    "JobEngineUnavailable",
    "JobNotFound",
    "ReportNotReady",
    "JobConflict",
]
