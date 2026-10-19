"""Correction-engine contract (Phase 3) and its construction point.

This module is the stable seam between the application and the mathematical
correction engine. It owns the data types, the input policy and the
:class:`CorrectionEngine` protocol. The implementation lives in
:mod:`app.correction`; the behavioral contract (HTTP surface, Phase 4 job
lifecycle) is in ``docs/correction-engine-contract.md``.

Phase 3 rules that the implementation honours:

* Validate every request with :func:`validate_request`, the single owner of
  the accepted-input policy (media types, per-file size limit, file count,
  and the presence of a mark scheme).
* Fail honestly: raise :class:`EngineError` subclasses whose messages are
  safe to show users. Never return fabricated or placeholder results.
* Report what could not be read, mapped or verified instead of awarding a
  silent zero. ``MarkedItem.status`` and ``review_flags`` carry that
  uncertainty; the deterministic checks in :mod:`app.correction.verify`
  never change a mark.
* ``SubmissionFile.path`` and any other server-side path stay out of HTTP
  responses; wire shapes carry filenames, sizes and media types only.

The Phase 3 engine processes one request synchronously. Job persistence and
the durable ``queued``/``processing`` lifecycle belong to Phase 4; the
implementation keeps a process-local registry only so the protocol methods
``get_job``/``get_report`` are usable and independently testable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable

# --- Input policy (kept in lockstep with the frontend's file validation) -----

ACCEPTED_MEDIA_TYPES = ("application/pdf", "image/png", "image/jpeg")
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_FILES = 12

# Question-level status values. A question that could not be read or mapped is
# never represented as a confirmed zero.
QUESTION_MARKED = "marked"
QUESTION_UNRESOLVED = "unresolved"
QUESTION_UNREADABLE = "unreadable"
QUESTION_MISSING = "missing"
QUESTION_AMBIGUOUS = "ambiguous"

QUESTION_STATUSES = (
    QUESTION_MARKED,
    QUESTION_UNRESOLVED,
    QUESTION_UNREADABLE,
    QUESTION_MISSING,
    QUESTION_AMBIGUOUS,
)

REPORT_COMPLETED = "completed"
REPORT_PARTIAL = "partial"


# --- Data model -------------------------------------------------------------


class JobStatus(str, Enum):
    """Lifecycle states of a correction job (see docs/correction-engine-contract.md)."""

    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class SubmissionFile:
    """One uploaded file.

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
    feedback_detail: str = "detailed"


@dataclass(frozen=True)
class CorrectionRequest:
    """Everything the engine needs to grade one batch of submissions.

    ``mark_scheme_files`` was added in Phase 3: the engine marks against a
    supplied mark scheme (file and/or ``assignment.mark_scheme`` text) and
    refuses to run without one. The field is additive, so existing callers
    that used only ``assignment.mark_scheme`` keep working.
    """

    files: tuple[SubmissionFile, ...]
    assignment: AssignmentContext
    options: CorrectionOptions = field(default_factory=CorrectionOptions)
    mark_scheme_files: tuple[SubmissionFile, ...] = ()


@dataclass(frozen=True)
class MarkedItem:
    """The verdict for one question or subquestion within a submission.

    ``awarded`` is ``None`` when the question could not be marked (unreadable,
    unmapped or missing). Zero is a real mark and is never used in place of
    "unknown". ``status`` is one of :data:`QUESTION_STATUSES`; ``review_flags``
    names why a human should look at the decision. No probabilistic confidence
    is exposed — only explicit uncertainty categories.
    """

    label: str
    awarded: float | None
    out_of: float | None
    feedback: str
    criteria: tuple[str, ...] = ()
    student_evidence: str = ""
    scheme_evidence: str = ""
    verification: str = ""
    student_answer: str = ""
    scheme_answer: str = ""
    status: str = QUESTION_MARKED
    warnings: tuple[str, ...] = ()
    review_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class CorrectionReport:
    """The grading output for one completed job.

    ``awarded`` and ``out_of`` are sums of the accepted question-level marks.
    ``percentage`` is present only when the report is complete and the total
    available marks are positive; an incomplete result never carries a
    misleading percentage. ``status`` is ``completed`` or ``partial``.
    """

    job_id: str
    summary: str
    awarded: float | None
    out_of: float | None
    items: tuple[MarkedItem, ...]
    status: str = REPORT_COMPLETED
    percentage: float | None = None
    review_required: bool = False
    unresolved: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    engine: str = ""
    created_at: str = ""


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


class ExtractionError(EngineError):
    """A submitted file could not be read as supported student work."""


class InvalidEngineOutput(EngineError):
    """The engine's result violated the result schema or marking rules."""


class ProviderError(EngineError):
    """The AI provider failed in a way that is safe to describe to the user."""


# --- Input policy -----------------------------------------------------------


def validate_request(request: CorrectionRequest) -> None:
    """Raise :class:`UnsupportedInputError` when a request breaks the policy.

    This function is the single owner of accepted-input rules on the backend.
    The engine calls it first; nothing downstream re-checks limits.

    A mark scheme is mandatory: the engine marks against it and will not
    invent marking criteria. It may be supplied as one or more files, as
    pasted text in ``assignment.mark_scheme``, or both.
    """
    if not request.files:
        raise UnsupportedInputError("No files were submitted. Attach at least one homework file.")
    if not request.assignment.title.strip():
        raise UnsupportedInputError("An assignment title is required before correction can start.")
    if not request.mark_scheme_files and not request.assignment.mark_scheme.strip():
        raise UnsupportedInputError(
            "A mark scheme is required. Attach the mark-scheme file or paste its text."
        )

    if request.options.feedback_detail not in ("brief", "detailed"):
        raise UnsupportedInputError(
            "Feedback detail must be 'brief' or 'detailed'."
        )
    if request.options.max_score is not None:
        max_score = request.options.max_score
        if (
            isinstance(max_score, bool)
            or not isinstance(max_score, (int, float))
            or not math.isfinite(float(max_score))
            or max_score <= 0
        ):
            raise UnsupportedInputError(
                "The expected total mark must be a positive number when supplied."
            )

    total_files = len(request.files) + len(request.mark_scheme_files)
    if total_files > MAX_FILES:
        raise UnsupportedInputError(
            f"Too many files were submitted ({total_files}). Attach at most {MAX_FILES} files."
        )

    for item in (*request.files, *request.mark_scheme_files):
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
    job methods are async because real engines call remote providers.
    """

    def describe(self) -> EngineInfo: ...

    async def submit(self, request: CorrectionRequest) -> CorrectionJob: ...

    async def get_job(self, job_id: str) -> CorrectionJob: ...

    async def get_report(self, job_id: str) -> CorrectionReport: ...


class UnavailableEngine:
    """The honest fallback: reports unavailability and invents nothing.

    Used when no AI provider is configured (or its configuration is invalid).
    Every job method raises :class:`EngineUnavailableError` rather than
    returning placeholder data, so no caller can mistake an unconfigured
    backend for a working correction pipeline.
    """

    def __init__(self, reason: str | None = None):
        self._reason = reason or (
            "No AI provider is configured. Set MC6_AI_API_KEY to enable correction."
        )

    def describe(self) -> EngineInfo:
        return EngineInfo(name="unavailable", available=False, reason=self._reason)

    async def submit(self, request: CorrectionRequest) -> CorrectionJob:
        raise EngineUnavailableError(self._reason)

    async def get_job(self, job_id: str) -> CorrectionJob:
        raise EngineUnavailableError(self._reason)

    async def get_report(self, job_id: str) -> CorrectionReport:
        raise EngineUnavailableError(self._reason)


def get_engine() -> CorrectionEngine:
    """Return the engine to use for correction jobs.

    This is the only construction point. It dispatches on provider
    configuration: with a key it returns the real Gemini-backed engine;
    without one it returns :class:`UnavailableEngine` with a user-safe reason.
    Callers depend only on the :class:`CorrectionEngine` protocol.
    """
    from .correction.service import create_engine

    return create_engine()
