"""The single persistence boundary for Math Checker V6.

Every SQL statement in the application lives here. API routes and services
depend on :class:`Storage` methods, never on the database directly.

Records are returned as frozen dataclasses from :mod:`app.models`. Writes that
touch more than one row (for example recording a result and marking its
submission graded) run in one SQLite transaction.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any, Mapping

from .db import Database
from .models import (
    DEFAULT_SETTINGS,
    SETTINGS_BY_KEY,
    Assignment,
    CorrectionOutcome,
    CorrectionResult,
    DatabaseStats,
    DatabaseStatus,
    SettingsValidationError,
    Student,
    Submission,
    SubmissionCounts,
    SubmissionStatus,
    is_finite_number,
    new_id,
    parse_stored_setting,
    serialise_setting_value,
    utc_now,
    validate_settings_update,
)

log = logging.getLogger("mathchecker.storage")

_UNSET = object()


class StorageError(RuntimeError):
    """Base class for storage-layer failures."""


class ValidationError(StorageError):
    """The supplied data violates a storage rule."""


class NotFoundError(StorageError):
    """A referenced record does not exist."""


class ConflictError(StorageError):
    """A uniqueness rule (or one-result-per-submission) was violated."""


class Storage:
    """High-level persistence interface backed by one SQLite database."""

    def __init__(self, database: Database):
        self.database = database

    # --- Settings ---------------------------------------------------------

    def get_settings(self) -> dict[str, Any]:
        """Return current settings merged over safe defaults.

        A corrupt stored value is logged by key and replaced by its default;
        it must never prevent the application from starting.
        """
        with self.database.connection() as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
        stored = {str(row["key"]): str(row["value"]) for row in rows}
        settings = dict(DEFAULT_SETTINGS)
        for key, definition in SETTINGS_BY_KEY.items():
            if key not in stored:
                continue
            try:
                settings[key] = parse_stored_setting(definition, stored[key])
            except SettingsValidationError:
                log.warning("ignoring invalid stored setting %s; using default", key)
        return settings

    def update_settings(self, changes: Mapping[str, Any]) -> dict[str, Any]:
        validated = validate_settings_update(changes)
        now = utc_now()
        with self.database.transaction() as conn:
            for key, value in validated.items():
                definition = SETTINGS_BY_KEY[key]
                conn.execute(
                    """
                    INSERT INTO settings(key, value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        updated_at = excluded.updated_at
                    """,
                    (key, serialise_setting_value(definition, value), now),
                )
        return self.get_settings()

    # --- Students ---------------------------------------------------------

    def create_student(
        self,
        display_name: str,
        *,
        email: str | None = None,
        external_id: str | None = None,
        student_id: str | None = None,
        created_at: str | None = None,
    ) -> Student:
        name = _required_text(display_name, "display_name")
        student_id = _record_id(student_id)
        now = _timestamp(created_at, "created_at") if created_at else utc_now()
        email = _optional_text(email, "email")
        external_id = _optional_text(external_id, "external_id")

        with self.database.transaction() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO students(id, display_name, email, external_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (student_id, name, email, external_id, now, now),
                )
            except sqlite3.IntegrityError as exc:
                raise ConflictError(
                    "A student with that id or external id already exists."
                ) from exc
            row = _fetch_student(conn, student_id)
        if row is None:  # pragma: no cover - defensive
            raise StorageError("Student was not stored.")
        return _student_from_row(row)

    def get_student(self, student_id: str) -> Student | None:
        with self.database.connection() as conn:
            row = _fetch_student(conn, student_id)
        return _student_from_row(row) if row else None

    def list_students(self) -> list[Student]:
        with self.database.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM students ORDER BY display_name, id"
            ).fetchall()
        return [_student_from_row(row) for row in rows]

    def update_student(
        self,
        student_id: str,
        *,
        display_name: Any = _UNSET,
        email: Any = _UNSET,
        external_id: Any = _UNSET,
    ) -> Student:
        with self.database.transaction() as conn:
            row = _fetch_student(conn, student_id)
            if row is None:
                raise NotFoundError("Student not found.")
            current = _student_from_row(row)
            name = (
                _required_text(display_name, "display_name")
                if display_name is not _UNSET
                else current.display_name
            )
            email_value = (
                _optional_text(email, "email") if email is not _UNSET else current.email
            )
            external_value = (
                _optional_text(external_id, "external_id")
                if external_id is not _UNSET
                else current.external_id
            )
            try:
                conn.execute(
                    """
                    UPDATE students
                    SET display_name = ?, email = ?, external_id = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (name, email_value, external_value, utc_now(), student_id),
                )
            except sqlite3.IntegrityError as exc:
                raise ConflictError(
                    "A student with that external id already exists."
                ) from exc
            updated = _fetch_student(conn, student_id)
        if updated is None:  # pragma: no cover - defensive
            raise StorageError("Student was not updated.")
        return _student_from_row(updated)

    # --- Assignments ------------------------------------------------------

    def create_assignment(
        self,
        title: str,
        *,
        qualification: str = "Edexcel IGCSE Mathematics",
        component: str = "",
        lesson_code: str | None = None,
        notes: str = "",
        max_score: float | None = None,
        assignment_id: str | None = None,
        created_at: str | None = None,
    ) -> Assignment:
        assignment_id = _record_id(assignment_id)
        clean_title = _required_text(title, "title")
        clean_qualification = _text(qualification, "qualification")
        clean_component = _text(component, "component")
        clean_lesson = _lesson_code(lesson_code)
        clean_notes = _text(notes, "notes")
        clean_max = _optional_number(max_score, "max_score")
        if clean_max is not None and clean_max < 0:
            raise ValidationError("max_score cannot be negative.")
        now = _timestamp(created_at, "created_at") if created_at else utc_now()

        with self.database.transaction() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO assignments(
                        id, title, qualification, component, lesson_code,
                        notes, max_score, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        assignment_id,
                        clean_title,
                        clean_qualification,
                        clean_component,
                        clean_lesson,
                        clean_notes,
                        clean_max,
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ConflictError("An assignment with that id already exists.") from exc
            row = _fetch_assignment(conn, assignment_id)
        if row is None:  # pragma: no cover - defensive
            raise StorageError("Assignment was not stored.")
        return _assignment_from_row(row)

    def get_assignment(self, assignment_id: str) -> Assignment | None:
        with self.database.connection() as conn:
            row = _fetch_assignment(conn, assignment_id)
        return _assignment_from_row(row) if row else None

    def list_assignments(self) -> list[Assignment]:
        with self.database.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM assignments ORDER BY created_at, id"
            ).fetchall()
        return [_assignment_from_row(row) for row in rows]

    def update_assignment(
        self,
        assignment_id: str,
        *,
        title: Any = _UNSET,
        qualification: Any = _UNSET,
        component: Any = _UNSET,
        lesson_code: Any = _UNSET,
        notes: Any = _UNSET,
        max_score: Any = _UNSET,
    ) -> Assignment:
        with self.database.transaction() as conn:
            row = _fetch_assignment(conn, assignment_id)
            if row is None:
                raise NotFoundError("Assignment not found.")
            current = _assignment_from_row(row)

            new_title = (
                _required_text(title, "title") if title is not _UNSET else current.title
            )
            new_qualification = (
                _text(qualification, "qualification")
                if qualification is not _UNSET
                else current.qualification
            )
            new_component = (
                _text(component, "component")
                if component is not _UNSET
                else current.component
            )
            new_lesson = (
                _lesson_code(lesson_code)
                if lesson_code is not _UNSET
                else current.lesson_code
            )
            new_notes = _text(notes, "notes") if notes is not _UNSET else current.notes
            new_max = (
                _optional_number(max_score, "max_score")
                if max_score is not _UNSET
                else current.max_score
            )
            if new_max is not None and new_max < 0:
                raise ValidationError("max_score cannot be negative.")

            conn.execute(
                """
                UPDATE assignments
                SET title = ?, qualification = ?, component = ?, lesson_code = ?,
                    notes = ?, max_score = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    new_title,
                    new_qualification,
                    new_component,
                    new_lesson,
                    new_notes,
                    new_max,
                    utc_now(),
                    assignment_id,
                ),
            )
            updated = _fetch_assignment(conn, assignment_id)
        if updated is None:  # pragma: no cover - defensive
            raise StorageError("Assignment was not updated.")
        return _assignment_from_row(updated)

    # --- Submissions ------------------------------------------------------

    def create_submission(
        self,
        assignment_id: str,
        student_id: str,
        status: SubmissionStatus | str,
        *,
        original_filename: str | None = None,
        media_type: str | None = None,
        size_bytes: int | None = None,
        submitted_at: str | None = None,
        submission_id: str | None = None,
        created_at: str | None = None,
    ) -> Submission:
        submission_status = _submission_status(status)
        if submission_status is SubmissionStatus.GRADED:
            raise ValidationError(
                "A graded submission is created by recording a correction result."
            )
        _require_record_exists(self.database, "assignments", assignment_id)
        _require_record_exists(self.database, "students", student_id)

        clean_filename = _optional_text(original_filename, "original_filename")
        clean_media = _optional_text(media_type, "media_type")
        clean_size = _optional_int(size_bytes, "size_bytes")
        if clean_size is not None and clean_size < 0:
            raise ValidationError("size_bytes cannot be negative.")
        if submission_status is SubmissionStatus.MISSING and (
            clean_filename is not None or clean_size is not None
        ):
            raise ValidationError("A missing submission cannot carry a file.")
        submitted_value = _submitted_at_for(submission_status, submitted_at)

        submission_id = _record_id(submission_id)
        now = _timestamp(created_at, "created_at") if created_at else utc_now()

        with self.database.transaction() as conn:
            existing = _fetch_submission_for(conn, assignment_id, student_id)
            if existing is not None:
                raise ConflictError(
                    "A submission already exists for this student and assignment."
                )
            try:
                conn.execute(
                    """
                    INSERT INTO submissions(
                        id, assignment_id, student_id, status, original_filename,
                        media_type, size_bytes, submitted_at, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        submission_id,
                        assignment_id,
                        student_id,
                        submission_status.value,
                        clean_filename,
                        clean_media,
                        clean_size,
                        submitted_value,
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ConflictError(
                    "A submission already exists for this student and assignment."
                ) from exc
            row = _fetch_submission(conn, submission_id)
        if row is None:  # pragma: no cover - defensive
            raise StorageError("Submission was not stored.")
        return _submission_from_row(row)

    def get_submission(self, submission_id: str) -> Submission | None:
        with self.database.connection() as conn:
            row = _fetch_submission(conn, submission_id)
        return _submission_from_row(row) if row else None

    def get_submission_for(
        self, assignment_id: str, student_id: str
    ) -> Submission | None:
        with self.database.connection() as conn:
            row = _fetch_submission_for(conn, assignment_id, student_id)
        return _submission_from_row(row) if row else None

    def list_submissions(
        self,
        *,
        assignment_id: str | None = None,
        student_id: str | None = None,
        status: SubmissionStatus | str | None = None,
    ) -> list[Submission]:
        clauses: list[str] = []
        params: list[Any] = []
        if assignment_id is not None:
            clauses.append("assignment_id = ?")
            params.append(assignment_id)
        if student_id is not None:
            clauses.append("student_id = ?")
            params.append(student_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(_submission_status(status).value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.database.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM submissions" + where + " ORDER BY created_at, id",
                tuple(params),
            ).fetchall()
        return [_submission_from_row(row) for row in rows]

    def update_submission_status(
        self,
        submission_id: str,
        status: SubmissionStatus | str,
        *,
        submitted_at: Any = _UNSET,
    ) -> Submission:
        target = _submission_status(status)
        if target is SubmissionStatus.GRADED:
            raise ValidationError(
                "A graded status is set by recording a correction result."
            )

        with self.database.transaction() as conn:
            row = _fetch_submission(conn, submission_id)
            if row is None:
                raise NotFoundError("Submission not found.")
            current = _submission_from_row(row)
            if current.status is SubmissionStatus.GRADED:
                raise ConflictError(
                    "A graded submission's status cannot be changed directly."
                )

            if target in (SubmissionStatus.MISSING, SubmissionStatus.DRAFT):
                if submitted_at not in (_UNSET, None):
                    raise ValidationError(
                        f"A {target.value} submission cannot have a submitted time."
                    )
                new_submitted = None
            else:
                if submitted_at is _UNSET:
                    new_submitted = current.submitted_at or utc_now()
                else:
                    new_submitted = (
                        _timestamp(submitted_at, "submitted_at")
                        if submitted_at is not None
                        else utc_now()
                    )

            conn.execute(
                """
                UPDATE submissions
                SET status = ?, submitted_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (target.value, new_submitted, utc_now(), submission_id),
            )
            updated = _fetch_submission(conn, submission_id)
        if updated is None:  # pragma: no cover - defensive
            raise StorageError("Submission was not updated.")
        return _submission_from_row(updated)

    # --- Correction results ----------------------------------------------

    def record_correction(
        self,
        submission_id: str,
        awarded: float | None,
        out_of: float | None,
        *,
        outcome: CorrectionOutcome | str = CorrectionOutcome.COMPLETED,
        summary: str = "",
        feedback: str = "",
        error: str | None = None,
        created_at: str | None = None,
    ) -> CorrectionResult:
        """Store one result and update its submission in one transaction.

        ``awarded=0`` is stored as a real zero. Missing marks must be passed as
        ``None`` and are only legal for a failed correction outcome.
        """
        result_outcome = _correction_outcome(outcome)
        result_id = new_id()
        now = _timestamp(created_at, "created_at") if created_at else utc_now()

        with self.database.transaction() as conn:
            row = _fetch_submission(conn, submission_id)
            if row is None:
                raise NotFoundError("Submission not found.")
            submission = _submission_from_row(row)
            if submission.status in (SubmissionStatus.MISSING, SubmissionStatus.DRAFT):
                raise ValidationError(
                    "A correction result requires submitted work, not a missing or draft submission."
                )
            if _fetch_correction_for_submission(conn, submission_id) is not None:
                raise ConflictError("This submission already has a correction result.")

            if result_outcome is CorrectionOutcome.COMPLETED:
                if not is_finite_number(awarded) or not is_finite_number(out_of):
                    raise ValidationError(
                        "A completed correction requires numeric awarded and out_of marks."
                    )
                awarded_value = float(awarded)
                out_of_value = float(out_of)
                if awarded_value < 0 or out_of_value < 0:
                    raise ValidationError("Marks cannot be negative.")
                if awarded_value > out_of_value:
                    raise ValidationError("Awarded marks cannot exceed the total available.")
                result_error = None
                new_status = SubmissionStatus.GRADED
            else:
                if awarded is not None or out_of is not None:
                    raise ValidationError(
                        "A failed correction must not carry awarded or out_of marks."
                    )
                awarded_value = None
                out_of_value = None
                result_error = _optional_text(error, "error") or "Correction failed."
                new_status = SubmissionStatus.FAILED

            conn.execute(
                """
                INSERT INTO correction_results(
                    id, submission_id, outcome, awarded, out_of, summary,
                    feedback, error, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result_id,
                    submission_id,
                    result_outcome.value,
                    awarded_value,
                    out_of_value,
                    _text(summary, "summary"),
                    _text(feedback, "feedback"),
                    result_error,
                    now,
                    now,
                ),
            )
            conn.execute(
                "UPDATE submissions SET status = ?, updated_at = ? WHERE id = ?",
                (new_status.value, now, submission_id),
            )
            result_row = _fetch_correction(conn, result_id)

        if result_row is None:  # pragma: no cover - defensive
            raise StorageError("Correction result was not stored.")
        return _correction_from_row(result_row)

    def get_correction_for_submission(
        self, submission_id: str
    ) -> CorrectionResult | None:
        with self.database.connection() as conn:
            row = _fetch_correction_for_submission(conn, submission_id)
        return _correction_from_row(row) if row else None

    # --- Status and statistics -------------------------------------------

    def database_status(self) -> DatabaseStatus:
        return self.database.status()

    def stats(self) -> DatabaseStats:
        with self.database.connection() as conn:
            students = _count(conn, "students")
            assignments = _count(conn, "assignments")

            status_rows = conn.execute(
                "SELECT status, COUNT(*) AS count FROM submissions GROUP BY status"
            ).fetchall()
            status_counts = {str(row["status"]): int(row["count"]) for row in status_rows}
            submissions = SubmissionCounts(
                missing=status_counts.get(SubmissionStatus.MISSING.value, 0),
                draft=status_counts.get(SubmissionStatus.DRAFT.value, 0),
                submitted=status_counts.get(SubmissionStatus.SUBMITTED.value, 0),
                graded=status_counts.get(SubmissionStatus.GRADED.value, 0),
                failed=status_counts.get(SubmissionStatus.FAILED.value, 0),
            )

            outcome_rows = conn.execute(
                "SELECT outcome, COUNT(*) AS count FROM correction_results GROUP BY outcome"
            ).fetchall()
            outcomes = {str(row["outcome"]): int(row["count"]) for row in outcome_rows}
            version_row = conn.execute("PRAGMA user_version").fetchone()

        return DatabaseStats(
            students=students,
            assignments=assignments,
            submissions=submissions,
            correction_results=sum(outcomes.values()),
            completed_results=outcomes.get(CorrectionOutcome.COMPLETED.value, 0),
            failed_results=outcomes.get(CorrectionOutcome.FAILED.value, 0),
            schema_version=int(version_row[0]) if version_row else 0,
        )


# --- Row mapping --------------------------------------------------------------

def _student_from_row(row: sqlite3.Row) -> Student:
    return Student(
        id=str(row["id"]),
        display_name=str(row["display_name"]),
        email=row["email"],
        external_id=row["external_id"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _assignment_from_row(row: sqlite3.Row) -> Assignment:
    return Assignment(
        id=str(row["id"]),
        title=str(row["title"]),
        qualification=str(row["qualification"]),
        component=str(row["component"]),
        lesson_code=row["lesson_code"],
        notes=str(row["notes"]),
        max_score=float(row["max_score"]) if row["max_score"] is not None else None,
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _submission_from_row(row: sqlite3.Row) -> Submission:
    return Submission(
        id=str(row["id"]),
        assignment_id=str(row["assignment_id"]),
        student_id=str(row["student_id"]),
        status=SubmissionStatus(str(row["status"])),
        original_filename=row["original_filename"],
        media_type=row["media_type"],
        size_bytes=int(row["size_bytes"]) if row["size_bytes"] is not None else None,
        submitted_at=row["submitted_at"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _correction_from_row(row: sqlite3.Row) -> CorrectionResult:
    return CorrectionResult(
        id=str(row["id"]),
        submission_id=str(row["submission_id"]),
        outcome=CorrectionOutcome(str(row["outcome"])),
        awarded=float(row["awarded"]) if row["awarded"] is not None else None,
        out_of=float(row["out_of"]) if row["out_of"] is not None else None,
        summary=str(row["summary"]),
        feedback=str(row["feedback"]),
        error=row["error"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


# --- Lookup helpers -----------------------------------------------------------

def _fetch_student(conn: sqlite3.Connection, student_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()


def _fetch_assignment(
    conn: sqlite3.Connection, assignment_id: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM assignments WHERE id = ?", (assignment_id,)
    ).fetchone()


def _fetch_submission(
    conn: sqlite3.Connection, submission_id: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM submissions WHERE id = ?", (submission_id,)
    ).fetchone()


def _fetch_submission_for(
    conn: sqlite3.Connection, assignment_id: str, student_id: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM submissions WHERE assignment_id = ? AND student_id = ?",
        (assignment_id, student_id),
    ).fetchone()


def _fetch_correction(
    conn: sqlite3.Connection, result_id: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM correction_results WHERE id = ?", (result_id,)
    ).fetchone()


def _fetch_correction_for_submission(
    conn: sqlite3.Connection, submission_id: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM correction_results WHERE submission_id = ?", (submission_id,)
    ).fetchone()


def _count(conn: sqlite3.Connection, table: str) -> int:
    # The table name is an internal constant, never user input.
    if table not in {"students", "assignments", "submissions", "correction_results"}:
        raise StorageError("Unknown statistics table.")
    row = conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
    return int(row["count"]) if row else 0


def _require_record_exists(database: Database, table: str, record_id: str) -> None:
    if table not in {"students", "assignments"}:
        raise StorageError("Unknown record table.")
    with database.connection() as conn:
        row = conn.execute(
            f"SELECT 1 FROM {table} WHERE id = ? LIMIT 1", (record_id,)
        ).fetchone()
    if row is None:
        raise NotFoundError(f"The referenced {table[:-1]} does not exist.")


# --- Validation helpers -------------------------------------------------------

def _record_id(value: str | None) -> str:
    if value is None:
        return new_id()
    return _required_text(value, "id")


def _text(value: Any, field: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be text.")
    return value.strip()


def _required_text(value: Any, field: str) -> str:
    text = _text(value, field)
    if not text:
        raise ValidationError(f"{field} is required.")
    return text


def _optional_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    text = _text(value, field)
    return text or None


def _lesson_code(value: Any) -> str | None:
    """Preserve a lesson code exactly as supplied; only blank means absent."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError("lesson_code must be text.")
    if not value.strip():
        return None
    return value


def _timestamp(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be a non-empty ISO-8601 timestamp.")
    return value.strip()


def _optional_int(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"{field} must be an integer.")
    return value


def _optional_number(value: Any, field: str) -> float | None:
    if value is None:
        return None
    if not is_finite_number(value):
        raise ValidationError(f"{field} must be a finite number.")
    return float(value)


def _submission_status(value: Any) -> SubmissionStatus:
    try:
        return SubmissionStatus(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(item.value for item in SubmissionStatus)
        raise ValidationError(f"status must be one of: {allowed}.") from exc


def _correction_outcome(value: Any) -> CorrectionOutcome:
    try:
        return CorrectionOutcome(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(item.value for item in CorrectionOutcome)
        raise ValidationError(f"outcome must be one of: {allowed}.") from exc


def _submitted_at_for(
    status: SubmissionStatus, submitted_at: str | None
) -> str | None:
    if status in (SubmissionStatus.MISSING, SubmissionStatus.DRAFT):
        if submitted_at is not None:
            raise ValidationError(
                f"A {status.value} submission cannot have a submitted time."
            )
        return None
    if submitted_at is None:
        return utc_now()
    return _timestamp(submitted_at, "submitted_at")
