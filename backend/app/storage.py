"""The single persistence boundary for Math Checker V6.

Every SQL statement in the application lives here. API routes and services
depend on :class:`Storage` methods, never on the database directly.

Records are returned as frozen dataclasses from :mod:`app.models`. Writes that
touch more than one row (for example recording a result and marking its
submission graded) run in one SQLite transaction.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Sequence
from typing import Any, Mapping

from .db import Database
from .engine import (
    ACCEPTED_MEDIA_TYPES,
    MAX_FILES,
    QUESTION_MARKED,
    QUESTION_STATUSES,
    REPORT_COMPLETED,
    REPORT_PARTIAL,
    CorrectionReport,
    JobStatus,
    MarkedItem,
)
from .models import (
    DEFAULT_SETTINGS,
    SETTINGS_BY_KEY,
    Assignment,
    CorrectionJobFile,
    CorrectionJobRecord,
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

# Raw Classroom states that mean "the student has handed something in".
_TURNED_IN_STATES = ("TURNED_IN", "STUDENT_EDITED_AFTER_TURN_IN")


def gc_extract_attachment_ids(submission: Mapping[str, Any]) -> list[str]:
    """Stable Drive file ids attached to one StudentSubmission."""
    ids: list[str] = []
    for attachment in (submission.get("assignmentSubmission") or {}).get(
        "attachments", []
    ) or []:
        drive = attachment.get("driveFile") or {}
        if drive.get("id"):
            ids.append(str(drive["id"]))
    return ids


def _classroom_due_str(item: Mapping[str, Any]) -> str | None:
    due = item.get("dueDate")
    if not due:
        return None
    due_time = item.get("dueTime") or {}
    return (
        f"{due.get('year')}-{due.get('month', 0):02d}-{due.get('day', 0):02d} "
        f"{due_time.get('hours', 0):02d}:{due_time.get('minutes', 0):02d}"
    )


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

    # --- Google Classroom (schema version 3) -----------------------------

    def classroom_courses_fresh(self, newer_than: float) -> list[dict]:
        with self.database.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM classroom_courses ORDER BY name"
            ).fetchall()
        if not rows:
            return []
        if min(float(row["fetched_at"]) for row in rows) < newer_than:
            return []
        return [dict(row) for row in rows]

    def classroom_replace_courses(
        self, courses: Sequence[Mapping[str, Any]], *, fetched_at: float
    ) -> None:
        with self.database.transaction() as conn:
            for course in courses:
                conn.execute(
                    """
                    INSERT INTO classroom_courses(
                        id, name, section, enrollment_code, state, update_time, fetched_at)
                    VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET
                        name=excluded.name, section=excluded.section,
                        enrollment_code=excluded.enrollment_code,
                        state=excluded.state, update_time=excluded.update_time,
                        fetched_at=excluded.fetched_at
                    """,
                    (
                        str(course.get("id") or ""),
                        str(course.get("name") or "Unnamed course"),
                        course.get("section"),
                        course.get("enrollmentCode"),
                        course.get("courseState") or course.get("state"),
                        course.get("updateTime"),
                        fetched_at,
                    ),
                )

    def classroom_course_cached(self, course_id: str) -> bool:
        with self.database.connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM classroom_courses WHERE id = ?", (course_id,)
            ).fetchone()
        return row is not None

    def classroom_course_of(self, coursework_id: str) -> str | None:
        """The cached course that owns this coursework (Google ids are unrelated).

        Coursework ids and course ids come from independent Google id spaces,
        so callers MUST resolve the parent course through cached data, never
        by parsing the coursework id.
        """
        with self.database.connection() as conn:
            row = conn.execute(
                "SELECT course_id FROM classroom_coursework WHERE id = ?",
                (coursework_id,),
            ).fetchone()
        return str(row["course_id"]) if row and row["course_id"] else None

    def classroom_coursework_fresh(self, course_id: str, newer_than: float) -> bool:
        with self.database.connection() as conn:
            row = conn.execute(
                "SELECT MAX(fetched_at) AS latest FROM classroom_coursework "
                "WHERE course_id = ?",
                (course_id,),
            ).fetchone()
        return bool(row and row["latest"] and float(row["latest"]) >= newer_than)

    def classroom_coursework_rows(self, course_id: str) -> list[dict]:
        with self.database.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM classroom_coursework WHERE course_id = ? "
                "AND deleted_in_classroom = 0 ORDER BY update_time DESC",
                (course_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def classroom_replace_coursework(
        self,
        course_id: str,
        items: Sequence[Mapping[str, Any]],
        *,
        fetched_at: float,
        live_ids: set[str],
    ) -> None:
        now = _timestamp(utc_now(), "fetched_at_iso")
        with self.database.transaction() as conn:
            for item in items:
                conn.execute(
                    """
                    INSERT INTO classroom_coursework(
                        id, course_id, title, classroom_title, max_points, state,
                        due_date, alternate_link, description, update_time,
                        fetched_at, managed, deleted_in_classroom)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,
                        COALESCE((SELECT managed FROM classroom_coursework WHERE id = ?), 0),
                        0)
                    ON CONFLICT(id) DO UPDATE SET
                        title=excluded.title, classroom_title=excluded.classroom_title,
                        max_points=excluded.max_points, state=excluded.state,
                        due_date=excluded.due_date,
                        alternate_link=excluded.alternate_link,
                        description=excluded.description,
                        update_time=excluded.update_time,
                        fetched_at=excluded.fetched_at,
                        deleted_in_classroom=0
                    """,
                    (
                        str(item.get("id") or ""),
                        course_id,
                        str(item.get("title") or "Untitled assignment"),
                        str(item.get("title") or ""),
                        item.get("maxPoints"),
                        item.get("state"),
                        _classroom_due_str(item),
                        item.get("alternateLink"),
                        item.get("description"),
                        item.get("updateTime"),
                        fetched_at,
                        str(item.get("id") or ""),
                    ),
                )
            # A coursework Classroom no longer lists is DELETED, not destroyed:
            # archive it so cached history survives without stale polling.
            existing = conn.execute(
                "SELECT id FROM classroom_coursework WHERE course_id = ? "
                "AND deleted_in_classroom = 0",
                (course_id,),
            ).fetchall()
            for row in existing:
                if str(row["id"]) in live_ids:
                    continue
                conn.execute(
                    "UPDATE classroom_coursework SET deleted_in_classroom = 1, "
                    "allowlisted = 0 WHERE id = ?",
                    (str(row["id"]),),
                )

    def classroom_record_managed_coursework(
        self, *, coursework_id: str, course_id: str, title: str,
        max_points: float | None = None, alternate_link: str | None = None,
    ) -> None:
        """Persist that THIS app created the coursework (managed = 1)."""
        now = _timestamp(utc_now(), "managed_iso")
        with self.database.transaction() as conn:
            conn.execute(
                """
                INSERT INTO classroom_coursework(
                    id, course_id, title, classroom_title, max_points, state,
                    alternate_link, fetched_at, managed, deleted_in_classroom)
                VALUES(?,?,?,?,?,?,?,? , 1, 0)
                ON CONFLICT(id) DO UPDATE SET
                    managed=1, title=excluded.title,
                    max_points=COALESCE(excluded.max_points, classroom_coursework.max_points),
                    alternate_link=COALESCE(excluded.alternate_link,
                                            classroom_coursework.alternate_link),
                    deleted_in_classroom=0
                """,
                (coursework_id, course_id, title, title, max_points, "PUBLISHED",
                 alternate_link, now),
            )

    def classroom_course_of_submission(self, submission_id: str) -> str | None:
        """The cached course that owns one student submission."""
        with self.database.connection() as conn:
            row = conn.execute(
                "SELECT course_id FROM classroom_submissions WHERE submission_id = ?",
                (submission_id,),
            ).fetchone()
        return str(row["course_id"]) if row and row["course_id"] else None

    def classroom_submission_rows(self, coursework_id: str) -> list[dict]:
        with self.database.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM classroom_submissions WHERE coursework_id = ? "
                "ORDER BY COALESCE(student_name, student_id)",
                (coursework_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def classroom_submissions_fresh(self, coursework_id: str, newer_than: float) -> bool:
        with self.database.connection() as conn:
            row = conn.execute(
                "SELECT MAX(last_synced_at) AS latest FROM classroom_submissions "
                "WHERE coursework_id = ?",
                (coursework_id,),
            ).fetchone()
        return bool(row and row["latest"] and float(row["latest"]) >= newer_than)

    def classroom_replace_submissions(
        self,
        coursework_id: str,
        submissions: Sequence[Mapping[str, Any]],
        *,
        roster: Mapping[str, Mapping[str, Any]],
        now_ts: float,
    ) -> None:
        with self.database.transaction() as conn:
            seen: set[str] = set()
            for submission in submissions:
                submission_id = str(submission.get("id") or "")
                if not submission_id:
                    continue
                seen.add(submission_id)
                profile = roster.get(submission.get("userId")) or {}
                attachments = gc_extract_attachment_ids(submission)
                conn.execute(
                    """
                    INSERT INTO classroom_submissions(
                        submission_id, course_id, coursework_id, student_id,
                        student_name, student_email, attachment_id, current_state,
                        previous_state, late, assigned_grade, draft_grade,
                        max_points, data_quality, last_synced_at, first_seen_at,
                        sync_version)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,
                           ?,?,?,?,?,
                           COALESCE((SELECT sync_version + 1
                                     FROM classroom_submissions
                                     WHERE submission_id = ?), 1))
                    ON CONFLICT(submission_id) DO UPDATE SET
                        student_name=excluded.student_name,
                        student_email=excluded.student_email,
                        previous_state=classroom_submissions.current_state,
                        current_state=excluded.current_state,
                        late=excluded.late,
                        assigned_grade=excluded.assigned_grade,
                        draft_grade=excluded.draft_grade,
                        max_points=excluded.max_points,
                        data_quality=excluded.data_quality,
                        sync_error=NULL,
                        last_synced_at=excluded.last_synced_at,
                        sync_version=classroom_submissions.sync_version + 1
                    """,
                    (
                        submission_id,
                        str(submission.get("courseId") or ""),
                        coursework_id,
                        str(submission.get("userId") or ""),
                        (profile.get("name") or {}).get("fullName"),
                        profile.get("emailAddress"),
                        attachments[0] if attachments else None,
                        str(submission.get("state") or "UNKNOWN"),
                        None,
                        int(bool(submission.get("late"))),
                        submission.get("assignedGrade"),
                        submission.get("draftGrade"),
                        submission.get("maxPoints") if "maxPoints" in submission else None,
                        "VERIFIED" if submission.get("state") in _TURNED_IN_STATES else "UNKNOWN",
                        now_ts,
                        now_ts,
                        submission_id,
                    ),
                )

    def classroom_link_job(self, submission_id: str, job_id: str) -> None:
        with self.database.transaction() as conn:
            conn.execute(
                "UPDATE classroom_submissions SET correction_job_id = ? "
                "WHERE submission_id = ?",
                (job_id, submission_id),
            )

    def classroom_submission_target(
        self, submission_id: str
    ) -> dict | None:
        """Stable-id mapping (course, coursework, student) for one submission."""
        with self.database.connection() as conn:
            row = conn.execute(
                """
                SELECT cs.submission_id, cs.course_id, cs.coursework_id,
                       cs.student_id, cs.correction_job_id, cw.managed,
                       cw.title
                  FROM classroom_submissions cs
                  LEFT JOIN classroom_coursework cw ON cw.id = cs.coursework_id
                 WHERE cs.submission_id = ?
                """,
                (submission_id,),
            ).fetchone()
        return dict(row) if row else None

    def classroom_insert_publish_op(
        self, *, coursework_id: str, submission_id: str, op_type: str,
        payload: str, student_id: str | None, job_id: str | None,
        now_iso: str, status: str = "pending",
    ) -> str:
        op_id = new_id()
        with self.database.transaction() as conn:
            conn.execute(
                """
                INSERT INTO classroom_publish_ops(
                    id, coursework_id, submission_id, student_id, op_type,
                    payload_json, status, result_job_id, created_at, updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    op_id, coursework_id, submission_id, student_id, op_type,
                    payload, status, job_id, now_iso, now_iso,
                ),
            )
        return op_id

    def classroom_finish_publish_op(
        self, op_id: str, *, status: str, message: str | None,
        http_status: int | None, error_code: str | None,
        drive_file_id: str | None, finished_at: str,
    ) -> dict:
        with self.database.transaction() as conn:
            conn.execute(
                """
                UPDATE classroom_publish_ops SET
                    status=?, message=?, http_status=?, error_code=?,
                    drive_file_id=?, finished_at=?, updated_at=?
                WHERE id=?
                """,
                (status, message, http_status, error_code, drive_file_id,
                 finished_at, finished_at, op_id),
            )
            row = conn.execute(
                "SELECT * FROM classroom_publish_ops WHERE id = ?", (op_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError("Classroom publish operation was not found.")
        return dict(row)

    def classroom_publish_ops(self, coursework_id: str, *, limit: int = 100) -> list[dict]:
        with self.database.connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM classroom_publish_ops WHERE coursework_id = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (coursework_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def classroom_canonical_report(self, submission_id: str) -> dict | None:
        with self.database.connection() as conn:
            row = conn.execute(
                "SELECT * FROM classroom_canonical_reports WHERE submission_id = ?",
                (submission_id,),
            ).fetchone()
        return dict(row) if row else None

    def classroom_record_canonical_report(
        self, submission_id: str, *, job_id: str, drive_file_id: str | None,
        now_iso: str,
    ) -> None:
        with self.database.transaction() as conn:
            conn.execute(
                """
                INSERT INTO classroom_canonical_reports(
                    submission_id, job_id, drive_file_id, updated_at)
                VALUES(?,?,?,?)
                ON CONFLICT(submission_id) DO UPDATE SET
                    job_id=excluded.job_id,
                    drive_file_id=excluded.drive_file_id,
                    updated_at=excluded.updated_at
                """,
                (submission_id, job_id, drive_file_id, now_iso),
            )

    # --- Correction jobs (Phase 4) ---------------------------------------

    def create_correction_job(
        self,
        *,
        job_id: str,
        assignment_title: str,
        instructions: str = "",
        mark_scheme_text: str = "",
        feedback_detail: str = "detailed",
        max_score: float | None = None,
        partial_credit: bool = True,
        files: Sequence[CorrectionJobFile],
        idempotency_key: str | None = None,
        created_at: str | None = None,
    ) -> CorrectionJobRecord:
        """Create a job in ``queued`` state and record its input metadata.

        File bytes are never handled here; the caller owns the upload
        workspace. ``mark_scheme_text`` is retained for the job runner only
        and is excluded from HTTP serialisation by the API layer.
        """
        clean_job_id = _required_text(job_id, "job_id")
        title = _required_text(assignment_title, "assignment_title")
        clean_instructions = _text(instructions, "instructions")
        scheme_text = _text(mark_scheme_text, "mark_scheme_text")
        clean_detail = _feedback_detail(feedback_detail)
        clean_max = _optional_number(max_score, "max_score")
        if clean_max is not None and clean_max <= 0:
            raise ValidationError("max_score must be positive when supplied.")
        if not isinstance(partial_credit, bool):
            raise ValidationError("partial_credit must be a boolean.")

        clean_files = tuple(_job_file(file) for file in files)
        if not clean_files:
            raise ValidationError("At least one submission file is required.")
        if len(clean_files) > MAX_FILES:
            raise ValidationError(f"At most {MAX_FILES} files can be attached.")
        roles = {file.role for file in clean_files}
        if "submission" not in roles:
            raise ValidationError("At least one student submission file is required.")
        if "mark_scheme" not in roles and not scheme_text.strip():
            raise ValidationError("A mark scheme file or pasted text is required.")
        keys = {(file.role, file.position) for file in clean_files}
        if len(keys) != len(clean_files):
            raise ValidationError("Correction file positions must be unique per role.")

        clean_key = _optional_text(idempotency_key, "idempotency_key")
        if clean_key is not None and len(clean_key) > 128:
            raise ValidationError("idempotency_key is too long.")
        now = _timestamp(created_at, "created_at") if created_at else utc_now()

        with self.database.transaction() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO correction_jobs(
                        id, status, assignment_title, instructions, mark_scheme_text,
                        feedback_detail, max_score, partial_credit, warnings_json,
                        idempotency_key, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, '[]', ?, ?, ?)
                    """,
                    (
                        clean_job_id,
                        JobStatus.QUEUED.value,
                        title,
                        clean_instructions,
                        scheme_text,
                        clean_detail,
                        clean_max,
                        1 if partial_credit else 0,
                        clean_key,
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ConflictError(
                    "A correction job with that id or request key already exists."
                ) from exc

            for file in clean_files:
                conn.execute(
                    """
                    INSERT INTO correction_job_files(
                        job_id, role, position, filename, media_type, size_bytes
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        clean_job_id,
                        file.role,
                        file.position,
                        file.filename,
                        file.media_type,
                        file.size_bytes,
                    ),
                )
            row = _fetch_job(conn, clean_job_id)
            file_rows = _fetch_job_files(conn, clean_job_id)
        if row is None:  # pragma: no cover - defensive
            raise StorageError("Correction job was not stored.")
        return _job_from_row(row, file_rows)

    def get_correction_job(self, job_id: str) -> CorrectionJobRecord | None:
        with self.database.connection() as conn:
            row = _fetch_job(conn, job_id)
            files = _fetch_job_files(conn, job_id) if row else []
        return _job_from_row(row, files) if row else None

    def get_correction_job_by_idempotency(
        self, idempotency_key: str
    ) -> CorrectionJobRecord | None:
        key = _required_text(idempotency_key, "idempotency_key")
        with self.database.connection() as conn:
            row = conn.execute(
                "SELECT * FROM correction_jobs WHERE idempotency_key = ?", (key,)
            ).fetchone()
            files = _fetch_job_files(conn, str(row["id"])) if row else []
        return _job_from_row(row, files) if row else None

    def list_correction_jobs(
        self,
        *,
        limit: int = 50,
        status: JobStatus | str | None = None,
    ) -> list[CorrectionJobRecord]:
        """Return recent jobs without their input file rows.

        File metadata is intentionally omitted from list responses; job detail
        includes it. This keeps the list query to one statement.
        """
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ValidationError("limit must be an integer between 1 and 200.")
        params: list[Any] = []
        where = ""
        if status is not None:
            where = " WHERE status = ?"
            params.append(_job_status(status).value)
        params.append(limit)
        with self.database.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM correction_jobs" + where + " ORDER BY created_at DESC, id DESC LIMIT ?",
                tuple(params),
            ).fetchall()
        return [_job_from_row(row) for row in rows]

    def mark_correction_job_processing(self, job_id: str) -> CorrectionJobRecord:
        """Atomically move a queued job to ``processing``.

        A job already processing is returned unchanged (idempotent claim); a
        terminal job is never reopened.
        """
        now = utc_now()
        with self.database.transaction() as conn:
            row = _fetch_job(conn, job_id)
            if row is None:
                raise NotFoundError("Correction job not found.")
            current = _job_from_row(row)
            if current.status is JobStatus.PROCESSING:
                files = _fetch_job_files(conn, job_id)
                return _job_from_row(row, files)
            if current.status is not JobStatus.QUEUED:
                raise ConflictError(
                    f"A {current.status.value} correction job cannot start processing."
                )
            conn.execute(
                """
                UPDATE correction_jobs
                SET status = ?, started_at = COALESCE(started_at, ?), updated_at = ?
                WHERE id = ?
                """,
                (JobStatus.PROCESSING.value, now, now, job_id),
            )
            updated = _fetch_job(conn, job_id)
            files = _fetch_job_files(conn, job_id)
        if updated is None:  # pragma: no cover - defensive
            raise StorageError("Correction job was not updated.")
        return _job_from_row(updated, files)

    def complete_correction_job(
        self, job_id: str, report: CorrectionReport
    ) -> CorrectionJobRecord:
        """Persist every question row and mark the job completed atomically.

        The job status is updated in the same transaction that inserts the
        items, so a completed job cannot exist without its results. A repeated
        completion is idempotent; a failed job is never overwritten.
        """
        _validate_report_for_storage(report, job_id)
        now = utc_now()
        with self.database.transaction() as conn:
            row = _fetch_job(conn, job_id)
            if row is None:
                raise NotFoundError("Correction job not found.")
            current = _job_from_row(row)
            if current.status is JobStatus.COMPLETED:
                files = _fetch_job_files(conn, job_id)
                return _job_from_row(row, files)
            if current.status is not JobStatus.PROCESSING:
                raise ConflictError(
                    f"A {current.status.value} correction job cannot be completed."
                )

            for position, item in enumerate(report.items):
                conn.execute(
                    """
                    INSERT INTO correction_items(
                        job_id, position, label, awarded, out_of, feedback,
                        criteria_json, student_evidence, scheme_evidence,
                        verification, student_answer, scheme_answer, status,
                        warnings_json, review_flags_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        position,
                        item.label,
                        item.awarded,
                        item.out_of,
                        item.feedback,
                        _json_text(item.criteria),
                        item.student_evidence,
                        item.scheme_evidence,
                        item.verification,
                        item.student_answer,
                        item.scheme_answer,
                        item.status,
                        _json_text(item.warnings),
                        _json_text(item.review_flags),
                    ),
                )
            conn.execute(
                """
                UPDATE correction_jobs
                SET status = ?, engine = ?, summary = ?, awarded = ?, out_of = ?,
                    percentage = ?, report_status = ?, review_required = ?,
                    warnings_json = ?, completed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    JobStatus.COMPLETED.value,
                    report.engine,
                    report.summary,
                    report.awarded,
                    report.out_of,
                    report.percentage,
                    report.status,
                    1 if report.review_required else 0,
                    _json_text(report.warnings),
                    now,
                    now,
                    job_id,
                ),
            )
            updated = _fetch_job(conn, job_id)
            files = _fetch_job_files(conn, job_id)
        if updated is None:  # pragma: no cover - defensive
            raise StorageError("Correction job was not completed.")
        return _job_from_row(updated, files)

    def fail_correction_job(
        self, job_id: str, error: str, *, completed_at: str | None = None
    ) -> CorrectionJobRecord:
        """Record a safe failure without ever replacing a completed result."""
        clean_error = _optional_text(error, "error") or "The correction failed."
        now = _timestamp(completed_at, "completed_at") if completed_at else utc_now()
        with self.database.transaction() as conn:
            row = _fetch_job(conn, job_id)
            if row is None:
                raise NotFoundError("Correction job not found.")
            current = _job_from_row(row)
            if current.status in (JobStatus.COMPLETED, JobStatus.FAILED):
                files = _fetch_job_files(conn, job_id)
                return _job_from_row(row, files)
            conn.execute(
                """
                UPDATE correction_jobs
                SET status = ?, error = ?, completed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (JobStatus.FAILED.value, clean_error, now, now, job_id),
            )
            updated = _fetch_job(conn, job_id)
            files = _fetch_job_files(conn, job_id)
        if updated is None:  # pragma: no cover - defensive
            raise StorageError("Correction job was not updated.")
        return _job_from_row(updated, files)

    def recover_interrupted_correction_jobs(
        self, error: str = "Processing was interrupted by an application restart."
    ) -> list[str]:
        """Mark leftover queued/processing jobs failed; return their ids."""
        clean_error = _optional_text(error, "error") or "Correction was interrupted."
        now = utc_now()
        with self.database.transaction() as conn:
            rows = conn.execute(
                "SELECT id FROM correction_jobs WHERE status IN (?, ?)",
                (JobStatus.QUEUED.value, JobStatus.PROCESSING.value),
            ).fetchall()
            job_ids = [str(row["id"]) for row in rows]
            if job_ids:
                conn.execute(
                    """
                    UPDATE correction_jobs
                    SET status = ?, error = ?, completed_at = ?, updated_at = ?
                    WHERE status IN (?, ?)
                    """,
                    (
                        JobStatus.FAILED.value,
                        clean_error,
                        now,
                        now,
                        JobStatus.QUEUED.value,
                        JobStatus.PROCESSING.value,
                    ),
                )
        return job_ids

    def get_correction_report(self, job_id: str) -> CorrectionReport | None:
        """Reconstruct a report from persisted rows (no engine call)."""
        job = self.get_correction_job(job_id)
        if job is None:
            raise NotFoundError("Correction job not found.")
        if job.status is not JobStatus.COMPLETED or job.report_status is None:
            return None
        with self.database.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM correction_items WHERE job_id = ? ORDER BY position",
                (job_id,),
            ).fetchall()
        if not rows:
            raise StorageError("The stored correction has no question results.")
        items = tuple(_item_from_row(row) for row in rows)
        return CorrectionReport(
            job_id=job.job_id,
            summary=job.summary,
            awarded=job.awarded,
            out_of=job.out_of,
            items=items,
            status=job.report_status,
            percentage=job.percentage,
            review_required=job.review_required,
            unresolved=tuple(item.label for item in items if item.status != QUESTION_MARKED),
            warnings=job.warnings,
            engine=job.engine,
            created_at=job.created_at,
        )

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


def _job_from_row(
    row: sqlite3.Row, files: Sequence[sqlite3.Row] = ()
) -> CorrectionJobRecord:
    return CorrectionJobRecord(
        job_id=str(row["id"]),
        status=JobStatus(str(row["status"])),
        assignment_title=str(row["assignment_title"]),
        instructions=str(row["instructions"]),
        mark_scheme_text=str(row["mark_scheme_text"]),
        feedback_detail=str(row["feedback_detail"]),
        max_score=float(row["max_score"]) if row["max_score"] is not None else None,
        partial_credit=bool(int(row["partial_credit"])),
        summary=str(row["summary"]),
        awarded=float(row["awarded"]) if row["awarded"] is not None else None,
        out_of=float(row["out_of"]) if row["out_of"] is not None else None,
        percentage=float(row["percentage"]) if row["percentage"] is not None else None,
        report_status=row["report_status"],
        review_required=bool(int(row["review_required"])),
        warnings=_json_list(row["warnings_json"], "warnings"),
        error=row["error"],
        engine=str(row["engine"]),
        created_at=str(row["created_at"]),
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        updated_at=str(row["updated_at"]),
        files=tuple(_job_file_from_row(file) for file in files),
    )


def _job_file_from_row(row: sqlite3.Row) -> CorrectionJobFile:
    return CorrectionJobFile(
        role=str(row["role"]),
        position=int(row["position"]),
        filename=str(row["filename"]),
        media_type=str(row["media_type"]),
        size_bytes=int(row["size_bytes"]),
    )


def _item_from_row(row: sqlite3.Row) -> MarkedItem:
    return MarkedItem(
        label=str(row["label"]),
        awarded=float(row["awarded"]) if row["awarded"] is not None else None,
        out_of=float(row["out_of"]) if row["out_of"] is not None else None,
        feedback=str(row["feedback"]),
        criteria=_json_list(row["criteria_json"], "criteria"),
        student_evidence=str(row["student_evidence"]),
        scheme_evidence=str(row["scheme_evidence"]),
        verification=str(row["verification"]),
        student_answer=str(row["student_answer"]),
        scheme_answer=str(row["scheme_answer"]),
        status=str(row["status"]),
        warnings=_json_list(row["warnings_json"], "warnings"),
        review_flags=_json_list(row["review_flags_json"], "review_flags"),
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


def _fetch_job(conn: sqlite3.Connection, job_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM correction_jobs WHERE id = ?", (job_id,)
    ).fetchone()


def _fetch_job_files(
    conn: sqlite3.Connection, job_id: str
) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT * FROM correction_job_files
        WHERE job_id = ?
        ORDER BY role, position
        """,
        (job_id,),
    ).fetchall()


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


def _job_status(value: Any) -> JobStatus:
    try:
        return JobStatus(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(item.value for item in JobStatus)
        raise ValidationError(f"status must be one of: {allowed}.") from exc


def _feedback_detail(value: Any) -> str:
    text = _required_text(value, "feedback_detail")
    if text not in ("brief", "detailed"):
        raise ValidationError("feedback_detail must be 'brief' or 'detailed'.")
    return text


def _job_file(value: Any) -> CorrectionJobFile:
    if not isinstance(value, CorrectionJobFile):
        raise ValidationError("files must be CorrectionJobFile records.")
    role = _required_text(value.role, "role")
    if role not in ("submission", "mark_scheme"):
        raise ValidationError("role must be 'submission' or 'mark_scheme'.")
    position = _optional_int(value.position, "position")
    if position is None or position < 0:
        raise ValidationError("position must be a non-negative integer.")
    filename = _required_text(value.filename, "filename")
    media_type = _required_text(value.media_type, "media_type")
    if media_type not in ACCEPTED_MEDIA_TYPES:
        raise ValidationError("media_type is not supported.")
    size_bytes = _optional_int(value.size_bytes, "size_bytes")
    if size_bytes is None or size_bytes <= 0:
        raise ValidationError("size_bytes must be positive.")
    return CorrectionJobFile(
        role=role,
        position=position,
        filename=filename,
        media_type=media_type,
        size_bytes=size_bytes,
    )


def _json_text(values: Sequence[str]) -> str:
    return json.dumps(list(values), ensure_ascii=False)


def _json_list(raw: Any, field: str) -> tuple[str, ...]:
    try:
        value = json.loads(str(raw))
    except (TypeError, ValueError) as exc:
        raise StorageError(f"Stored {field} data is unreadable.") from exc
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise StorageError(f"Stored {field} data is unreadable.")
    return tuple(value)


def _validate_report_for_storage(report: CorrectionReport, job_id: str) -> None:
    """Re-check the engine's report invariants at the persistence boundary."""
    if not isinstance(report, CorrectionReport):
        raise StorageError("The engine did not return a correction report.")
    if report.job_id != job_id:
        raise StorageError("The engine report does not belong to this job.")
    if report.status not in (REPORT_COMPLETED, REPORT_PARTIAL):
        raise StorageError("The engine report has an unknown status.")
    if not report.items:
        raise StorageError("The engine report contains no question results.")

    labels: set[str] = set()
    awarded_values: list[float] = []
    maxima: list[float] = []
    all_maxima_known = True
    for item in report.items:
        if item.label in labels:
            raise StorageError("The engine report contains duplicate question labels.")
        labels.add(item.label)
        if item.status not in QUESTION_STATUSES:
            raise StorageError("The engine report contains an unknown question status.")
        if item.awarded is not None:
            if not is_finite_number(item.awarded) or item.awarded < 0:
                raise StorageError("The engine report contains an invalid mark.")
            awarded_values.append(float(item.awarded))
        if item.out_of is not None:
            if not is_finite_number(item.out_of) or item.out_of < 0:
                raise StorageError("The engine report contains an invalid maximum.")
            maxima.append(float(item.out_of))
        else:
            all_maxima_known = False
        if item.awarded is not None and item.out_of is not None and item.awarded > item.out_of:
            raise StorageError("The engine report awards more than a question maximum.")
        if item.status == QUESTION_MARKED and item.awarded is None:
            raise StorageError("A resolved question has no mark.")
        if item.status != QUESTION_MARKED and item.awarded is not None:
            raise StorageError("An unresolved question carries a mark.")

    expected_awarded = float(sum(awarded_values)) if awarded_values else None
    if not _same_total(report.awarded, expected_awarded):
        raise StorageError("The engine report total does not match its question results.")
    expected_out_of = float(sum(maxima)) if all_maxima_known else None
    if not _same_total(report.out_of, expected_out_of):
        raise StorageError("The engine report maximum does not match its question results.")

    expected_unresolved = tuple(
        item.label for item in report.items if item.status != QUESTION_MARKED
    )
    if set(report.unresolved) != set(expected_unresolved):
        raise StorageError("The engine report's unresolved list is inconsistent.")

    if report.status == REPORT_COMPLETED:
        if (
            expected_unresolved
            or not all_maxima_known
            or expected_awarded is None
            or report.percentage is None
        ):
            raise StorageError("A completed report is incomplete.")
    elif report.percentage is not None:
        raise StorageError("A partial report must not carry a percentage.")

    if report.percentage is not None:
        if not is_finite_number(report.percentage) or not 0 <= report.percentage <= 100:
            raise StorageError("The engine report contains an invalid percentage.")
        if report.status == REPORT_COMPLETED and report.out_of and report.out_of > 0:
            expected_percentage = round((report.awarded or 0.0) / report.out_of * 100.0, 2)
            if abs(report.percentage - expected_percentage) > 1e-9:
                raise StorageError("The engine report percentage is inconsistent.")


def _same_total(value: float | None, expected: float | None) -> bool:
    if value is None or expected is None:
        return value is None and expected is None
    if not is_finite_number(value):
        return False
    return abs(float(value) - expected) <= 1e-9


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
