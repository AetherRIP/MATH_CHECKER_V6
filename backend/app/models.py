"""Core data models, enums and settings definitions for Math Checker V6.

This module is deliberately free of database and HTTP code. It is the shared
vocabulary used by the storage layer, services and (later) API routes.

Storage rules represented here:

* Marks are ``None`` only when there is no mark. A zero mark is a real value.
* Submission states distinguish missing work, drafts, submitted work, graded
  work and failed processing.
* Assignment lesson codes are opaque text: they are never parsed, normalised
  or lower-cased by this application.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

from .engine import JobStatus


class SubmissionStatus(str, Enum):
    """Lifecycle of one student's work for one assignment."""

    MISSING = "missing"
    DRAFT = "draft"
    SUBMITTED = "submitted"
    GRADED = "graded"
    FAILED = "failed"


class CorrectionOutcome(str, Enum):
    """Outcome of one correction result."""

    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class Student:
    id: str
    display_name: str
    email: str | None
    external_id: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Assignment:
    id: str
    title: str
    qualification: str
    component: str
    lesson_code: str | None
    notes: str
    max_score: float | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Submission:
    id: str
    assignment_id: str
    student_id: str
    status: SubmissionStatus
    original_filename: str | None
    media_type: str | None
    size_bytes: int | None
    submitted_at: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class CorrectionResult:
    id: str
    submission_id: str
    outcome: CorrectionOutcome
    awarded: float | None
    out_of: float | None
    summary: str
    feedback: str
    error: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class CorrectionJobFile:
    """Metadata for one uploaded input. The server-side path is never stored."""

    role: str  # "submission" | "mark_scheme"
    position: int
    filename: str
    media_type: str
    size_bytes: int


@dataclass(frozen=True)
class CorrectionJobRecord:
    """Durable state of one correction job.

    ``mark_scheme_text`` is retained only so a queued/processing job can be
    run after a restart; HTTP responses never include it. ``files`` are
    metadata only. A completed job has ``report_status`` and per-question
    rows; a failed job has an error and no report.
    """

    job_id: str
    status: JobStatus
    assignment_title: str
    instructions: str
    mark_scheme_text: str
    feedback_detail: str
    max_score: float | None
    partial_credit: bool
    summary: str
    awarded: float | None
    out_of: float | None
    percentage: float | None
    report_status: str | None
    review_required: bool
    warnings: tuple[str, ...]
    error: str | None
    engine: str
    created_at: str
    started_at: str | None
    completed_at: str | None
    updated_at: str
    files: tuple[CorrectionJobFile, ...] = ()


@dataclass(frozen=True)
class SubmissionCounts:
    missing: int = 0
    draft: int = 0
    submitted: int = 0
    graded: int = 0
    failed: int = 0

    @property
    def total(self) -> int:
        return self.missing + self.draft + self.submitted + self.graded + self.failed

    def as_dict(self) -> dict[str, int]:
        return {
            "total": self.total,
            "missing": self.missing,
            "draft": self.draft,
            "submitted": self.submitted,
            "graded": self.graded,
            "failed": self.failed,
        }


@dataclass(frozen=True)
class DatabaseStatus:
    ready: bool
    schema_version: int | None = None
    detail: str | None = None


@dataclass(frozen=True)
class DatabaseStats:
    students: int
    assignments: int
    submissions: SubmissionCounts
    correction_results: int
    completed_results: int
    failed_results: int
    schema_version: int

    def as_counts(self) -> dict[str, Any]:
        return {
            "students": self.students,
            "assignments": self.assignments,
            "submissions": self.submissions.as_dict(),
            "correction_results": self.correction_results,
            "completed_results": self.completed_results,
            "failed_results": self.failed_results,
        }


# --- Settings -----------------------------------------------------------------

class SettingsValidationError(ValueError):
    """Raised when a settings update is unknown, empty or invalid."""


@dataclass(frozen=True)
class SettingDefinition:
    key: str
    kind: str  # "int" | "choice"
    default: Any
    label: str
    minimum: int | None = None
    maximum: int | None = None
    choices: tuple[str, ...] = ()


SETTING_DEFINITIONS: tuple[SettingDefinition, ...] = (
    SettingDefinition(
        key="max_upload_mb",
        kind="int",
        default=25,
        label="Maximum upload size (MB)",
        minimum=1,
        maximum=25,
    ),
    SettingDefinition(
        key="default_feedback_detail",
        kind="choice",
        default="detailed",
        label="Default feedback detail",
        choices=("brief", "detailed"),
    ),
)

SETTINGS_BY_KEY = {definition.key: definition for definition in SETTING_DEFINITIONS}
DEFAULT_SETTINGS = {definition.key: definition.default for definition in SETTING_DEFINITIONS}


def validate_settings_update(changes: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a partial settings update and return the normalised values.

    The settings table stores scalar values only. Unknown keys are rejected
    rather than ignored so a typo can never appear to have been saved.
    """
    if not isinstance(changes, Mapping):
        raise SettingsValidationError("Settings must be an object of key/value pairs.")
    if not changes:
        raise SettingsValidationError("At least one setting must be provided.")

    unknown = sorted(set(changes) - set(SETTINGS_BY_KEY))
    if unknown:
        raise SettingsValidationError(
            "Unknown setting" + ("s" if len(unknown) > 1 else "") + ": " + ", ".join(unknown)
        )

    validated: dict[str, Any] = {}
    for key, value in changes.items():
        validated[key] = _validate_setting_value(SETTINGS_BY_KEY[key], value)
    return validated


def _validate_setting_value(definition: SettingDefinition, value: Any) -> Any:
    if definition.kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise SettingsValidationError(f"{definition.key} must be an integer.")
        if definition.minimum is not None and value < definition.minimum:
            raise SettingsValidationError(
                f"{definition.key} must be at least {definition.minimum}."
            )
        if definition.maximum is not None and value > definition.maximum:
            raise SettingsValidationError(
                f"{definition.key} must be at most {definition.maximum}."
            )
        return value

    if definition.kind == "choice":
        if not isinstance(value, str) or value not in definition.choices:
            choices = ", ".join(definition.choices)
            raise SettingsValidationError(f"{definition.key} must be one of: {choices}.")
        return value

    raise SettingsValidationError(f"{definition.key} has an unsupported setting type.")


def parse_stored_setting(definition: SettingDefinition, raw: str) -> Any:
    """Parse one stored text value, raising SettingsValidationError if corrupt."""
    if definition.kind == "int":
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise SettingsValidationError(f"{definition.key} is not a valid integer.") from exc
        return _validate_setting_value(definition, value)

    if definition.kind == "choice":
        return _validate_setting_value(definition, raw)

    raise SettingsValidationError(f"{definition.key} has an unsupported setting type.")


def serialise_setting_value(definition: SettingDefinition, value: Any) -> str:
    """Serialise a validated setting value for the settings table."""
    if definition.kind == "int":
        return str(int(value))
    if definition.kind == "choice":
        return str(value)
    raise SettingsValidationError(f"{definition.key} has an unsupported setting type.")


# --- Shared helpers -----------------------------------------------------------

def new_id() -> str:
    """Return an opaque identifier for a new record."""
    return uuid.uuid4().hex


def utc_now() -> str:
    """Return the current time as an ISO-8601 UTC string."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def is_finite_number(value: Any) -> bool:
    """True for real, finite int/float values (bools are not numbers here)."""
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )
