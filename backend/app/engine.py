"""Future correction-engine contract (Phase 3), and the current honest stub.

This module is the backend's integration seam for AI correction. It is the
executable half of the contract: the data types and the
:class:`CorrectionEngine` protocol that Phase 3 implements. The HTTP surface,
job lifecycle and frontend wiring are specified in
``docs/correction-engine-contract.md``.

The current build ships only :class:`UnavailableEngine` — a stub that reports
honestly that correction is not available yet and raises
:class:`EngineUnavailableError` instead of inventing results. No engine code
exists here, by design.

Rules for Phase 3 implementations:

* Implement :class:`CorrectionEngine` and register it in :func:`get_engine`.
* Validate every request with :func:`validate_request`, the single owner of
  the accepted-input policy (media types, per-file size limit).
* Fail honestly: raise :class:`EngineError` subclasses whose messages are
  safe to show users. Never return fabricated or placeholder results.
* ``SubmissionFile.path`` and any other server-side path stay out of HTTP
  responses; wire shapes carry filenames and sizes only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable

# --- Input policy (kept in lockstep with the frontend's file validation) -----

ACCEPTED_MEDIA_TYPES = ("application/pdf", "image/png", "image/jpeg")
MAX_FILE_BYTES = 25 * 1024 * 1024


# --- Data model -------------------------------------------------------------


class JobStatus(str, Enum):
    """Lifecycle states of a correction job (see docs/correction-engine-contract.md)."""

    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class SubmissionFile:
    """One uploaded homework file.

    ``path`` is server-side only and must never appear in an HTTP response;
    wire shapes carry ``filename``, ``media_type`` and ``size_bytes``.
    """

    path: Path
    filename: str
    media_type: str
    size_bytes: int


@dataclass(frozen=True)
class AssignmentContext:
    """What the student's homework is about, as entered in the UI."""

    title: str
    instructions: str = ""
    mark_scheme: str = ""


@dataclass(frozen=True)
class CorrectionOptions:
    """Grading preferences chosen on the correction page."""

    partial_credit: bool = True
    max_score: float | None = None


@dataclass(frozen=True)
class CorrectionRequest:
    """Everything the engine needs to grade one batch of submissions."""

    files: tuple[SubmissionFile, ...]
    assignment: AssignmentContext
    options: CorrectionOptions = field(default_factory=CorrectionOptions)


@dataclass(frozen=True)
class MarkedItem:
    """The verdict for one question or task within a submission."""

    label: str
    awarded: float | None
    out_of: float | None
    feedback: str


@dataclass(frozen=True)
class CorrectionReport:
    """The grading output for one completed job."""

    job_id: str
    summary: str
    awarded: float | None
    out_of: float | None
    items: tuple[MarkedItem, ...]


@dataclass(frozen=True)
class CorrectionJob:
    """Job state as exposed to the API layer.

    ``files`` lists filenames only — never server-side paths.
    """

    job_id: str
    status: JobStatus
    submitted_at: str  # ISO 8601, UTC
    files: tuple[str, ...]
    error: str | None = None


@dataclass(frozen=True)
class EngineInfo:
    """What the engine says about itself; drives readiness UI honestly."""

    name: str
    available: bool
    reason: str | None = None


# --- Errors (messages are user-safe by contract) -----------------------------


class EngineError(Exception):
    """Base class for engine failures. ``args[0]`` is safe to show users."""


class EngineUnavailableError(EngineError):
    """The engine cannot run at all (e.g. no provider configured yet)."""


class UnsupportedInputError(EngineError):
    """The request violates the input policy enforced by validate_request."""


class JobNotFoundError(EngineError):
    """The requested job id does not exist (or never existed)."""


# --- Input policy -----------------------------------------------------------


def validate_request(request: CorrectionRequest) -> None:
    """Raise :class:`UnsupportedInputError` when a request breaks the policy.

    This function is the single owner of accepted-input rules on the backend.
    Phase 3 engines must call it first; nothing downstream re-checks limits.
    """
    if not request.files:
        raise UnsupportedInputError("No files were submitted. Attach at least one homework file.")
    for item in request.files:
        if item.media_type not in ACCEPTED_MEDIA_TYPES:
            raise UnsupportedInputError(
                f"'{item.filename}' is not a supported file type. Use PDF, PNG or JPEG."
            )
        if item.size_bytes <= 0:
            raise UnsupportedInputError(f"'{item.filename}' is empty.")
        if item.size_bytes > MAX_FILE_BYTES:
            raise UnsupportedInputError(f"'{item.filename}' is larger than the 25 MB limit.")


# --- The engine interface ---------------------------------------------------


@runtime_checkable
class CorrectionEngine(Protocol):
    """What every correction engine implements.

    ``describe`` is synchronous and cheap (used by readiness checks). The
    job methods are async because real engines will call remote providers.
    """

    def describe(self) -> EngineInfo: ...

    async def submit(self, request: CorrectionRequest) -> CorrectionJob: ...

    async def get_job(self, job_id: str) -> CorrectionJob: ...

    async def get_report(self, job_id: str) -> CorrectionReport: ...


class UnavailableEngine:
    """The honest stub: reports unavailability and invents nothing.

    Every job method raises :class:`EngineUnavailableError` rather than
    returning placeholder data, so no caller can mistake the backend
    foundation for a working correction pipeline.
    """

    _REASON = "The correction engine ships in a later phase (Phase 3); no jobs can run yet."

    def describe(self) -> EngineInfo:
        return EngineInfo(name="unavailable", available=False, reason=self._REASON)

    async def submit(self, request: CorrectionRequest) -> CorrectionJob:
        raise EngineUnavailableError(self._REASON)

    async def get_job(self, job_id: str) -> CorrectionJob:
        raise EngineUnavailableError(self._REASON)

    async def get_report(self, job_id: str) -> CorrectionReport:
        raise EngineUnavailableError(self._REASON)


def get_engine() -> CorrectionEngine:
    """Return the engine to use for correction jobs.

    The current build always returns :class:`UnavailableEngine`. Phase 3
    dispatches here on provider configuration and registers real engines —
    callers depend only on the :class:`CorrectionEngine` protocol, never on a
    concrete engine class.
    """
    return UnavailableEngine()
