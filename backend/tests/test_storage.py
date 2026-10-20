"""Tests for the storage boundary and its integrity rules."""

from __future__ import annotations

import logging

import pytest

from app.db import Database
from app.models import (
    CorrectionOutcome,
    SettingsValidationError,
    SubmissionStatus,
)
from app.storage import (
    ConflictError,
    NotFoundError,
    Storage,
    ValidationError,
)


@pytest.fixture()
def storage(tmp_path):
    database = Database(tmp_path / "app.db")
    database.initialize()
    return Storage(database)


def make_student(storage, name="Ada Lovelace", external_id=None):
    return storage.create_student(name, external_id=external_id)


def make_assignment(storage, title="Number homework", lesson_code="CH1L1", max_score=10):
    return storage.create_assignment(title, lesson_code=lesson_code, max_score=max_score)


def test_student_crud_and_external_id_uniqueness(storage):
    student = make_student(storage, "Ada Lovelace", "ada")
    assert storage.get_student(student.id) == student
    assert storage.list_students() == [student]

    updated = storage.update_student(
        student.id, display_name="Ada King", email="ada@example.test"
    )
    assert updated.display_name == "Ada King"
    assert updated.email == "ada@example.test"
    assert storage.get_student(student.id).display_name == "Ada King"

    with pytest.raises(ConflictError):
        make_student(storage, "Another Ada", "ada")
    with pytest.raises(NotFoundError):
        storage.update_student("missing", display_name="Nobody")


def test_assignment_crud_preserves_lesson_codes_exactly(storage):
    first = make_assignment(storage, "Lesson one", "CH1L1")
    later = make_assignment(storage, "Lesson thirteen", "CH1L13")
    duplicate_code = make_assignment(storage, "Another lesson one", "CH1L1")

    assert first.lesson_code == "CH1L1"
    assert later.lesson_code == "CH1L13"
    assert duplicate_code.lesson_code == "CH1L1"
    assert first.lesson_code != later.lesson_code

    updated = storage.update_assignment(
        later.id, title="Updated thirteen", lesson_code="CH1L14"
    )
    assert updated.title == "Updated thirteen"
    assert updated.lesson_code == "CH1L14"
    assert storage.get_assignment(first.id).lesson_code == "CH1L1"

    with pytest.raises(NotFoundError):
        storage.update_assignment("missing", title="Nope")


def test_missing_draft_and_submitted_are_distinct(storage):
    student = make_student(storage)
    missing_assignment = make_assignment(storage, "Missing", "CH1L1")
    draft_assignment = make_assignment(storage, "Draft", "CH1L2")
    submitted_assignment = make_assignment(storage, "Submitted", "CH1L3")

    missing = storage.create_submission(
        missing_assignment.id, student.id, SubmissionStatus.MISSING
    )
    draft = storage.create_submission(
        draft_assignment.id,
        student.id,
        SubmissionStatus.DRAFT,
        original_filename="draft.png",
        media_type="image/png",
        size_bytes=10,
    )
    submitted = storage.create_submission(
        submitted_assignment.id,
        student.id,
        SubmissionStatus.SUBMITTED,
        original_filename="work.pdf",
        media_type="application/pdf",
        size_bytes=20,
        submitted_at="2026-10-01T09:00:00+00:00",
    )

    assert missing.status is SubmissionStatus.MISSING
    assert draft.status is SubmissionStatus.DRAFT
    assert submitted.status is SubmissionStatus.SUBMITTED
    assert missing.submitted_at is None
    assert draft.submitted_at is None
    assert submitted.submitted_at == "2026-10-01T09:00:00+00:00"

    assert storage.list_submissions(status="missing") == [missing]
    assert storage.list_submissions(status="draft") == [draft]
    assert storage.list_submissions(status="submitted") == [submitted]


def test_zero_grade_is_stored_and_retrieved_as_zero(storage):
    student = make_student(storage)
    assignment = make_assignment(storage, max_score=10)
    submission = storage.create_submission(
        assignment.id,
        student.id,
        SubmissionStatus.SUBMITTED,
        submitted_at="2026-10-01T09:00:00+00:00",
    )

    result = storage.record_correction(
        submission.id,
        0.0,
        10.0,
        summary="No marks earned.",
        feedback="All working is incorrect.",
    )

    assert result.awarded == 0.0
    assert result.awarded is not None
    assert result.out_of == 10.0
    assert result.outcome is CorrectionOutcome.COMPLETED
    assert storage.get_correction_for_submission(submission.id) == result
    assert storage.get_submission(submission.id).status is SubmissionStatus.GRADED

    stats = storage.stats()
    assert stats.submissions.graded == 1
    assert stats.completed_results == 1


def test_missing_and_draft_submissions_cannot_be_graded(storage):
    student = make_student(storage)
    missing_assignment = make_assignment(storage, "Missing", "CH1L1")
    draft_assignment = make_assignment(storage, "Draft", "CH1L2")
    missing = storage.create_submission(
        missing_assignment.id, student.id, SubmissionStatus.MISSING
    )
    draft = storage.create_submission(
        draft_assignment.id, student.id, SubmissionStatus.DRAFT
    )

    for submission in (missing, draft):
        with pytest.raises(ValidationError):
            storage.record_correction(submission.id, 1.0, 10.0)
        assert storage.get_submission(submission.id).status is submission.status


def test_invalid_marks_are_rejected_without_writing_a_result(storage):
    student = make_student(storage)
    assignment = make_assignment(storage)
    submission = storage.create_submission(
        assignment.id, student.id, SubmissionStatus.SUBMITTED
    )

    for awarded, out_of in ((-1, 10), (11, 10), (1, -1), ("1", 10), (True, 10)):
        with pytest.raises(ValidationError):
            storage.record_correction(submission.id, awarded, out_of)

    assert storage.get_correction_for_submission(submission.id) is None
    assert storage.get_submission(submission.id).status is SubmissionStatus.SUBMITTED


def test_failed_correction_is_distinct_from_a_graded_zero(storage):
    student = make_student(storage)
    assignment = make_assignment(storage)
    submission = storage.create_submission(
        assignment.id, student.id, SubmissionStatus.SUBMITTED
    )

    result = storage.record_correction(
        submission.id,
        None,
        None,
        outcome=CorrectionOutcome.FAILED,
        summary="Provider unavailable.",
        error="The correction provider could not be reached.",
    )

    assert result.outcome is CorrectionOutcome.FAILED
    assert result.awarded is None
    assert result.out_of is None
    assert result.error
    assert storage.get_submission(submission.id).status is SubmissionStatus.FAILED
    assert storage.stats().failed_results == 1
    assert storage.stats().completed_results == 0

    # A failed outcome must never carry marks, and the original submission
    # keeps its failed result rather than being silently replaced.
    other_assignment = make_assignment(storage, "Other", "CH1L9")
    other = storage.create_submission(
        other_assignment.id, student.id, SubmissionStatus.SUBMITTED
    )
    with pytest.raises(ValidationError):
        storage.record_correction(
            other.id, 0.0, 10.0, outcome=CorrectionOutcome.FAILED
        )
    with pytest.raises(ConflictError):
        storage.record_correction(submission.id, 0.0, 10.0)


def test_one_correction_result_per_submission(storage):
    student = make_student(storage)
    assignment = make_assignment(storage)
    submission = storage.create_submission(
        assignment.id, student.id, SubmissionStatus.SUBMITTED
    )
    storage.record_correction(submission.id, 0.0, 10.0)

    with pytest.raises(ConflictError):
        storage.record_correction(submission.id, 1.0, 10.0)


def test_submission_creation_and_update_rules(storage):
    student = make_student(storage)
    assignment = make_assignment(storage)

    with pytest.raises(ValidationError):
        storage.create_submission(assignment.id, student.id, SubmissionStatus.GRADED)
    with pytest.raises(ValidationError):
        storage.create_submission(
            assignment.id,
            student.id,
            SubmissionStatus.MISSING,
            original_filename="not-really-missing.pdf",
        )
    with pytest.raises(ValidationError):
        storage.create_submission(
            assignment.id,
            student.id,
            SubmissionStatus.DRAFT,
            submitted_at="2026-10-01T09:00:00+00:00",
        )

    submission = storage.create_submission(
        assignment.id,
        student.id,
        SubmissionStatus.SUBMITTED,
        submitted_at="2026-10-01T09:00:00+00:00",
    )
    with pytest.raises(ConflictError):
        storage.create_submission(assignment.id, student.id, SubmissionStatus.DRAFT)
    with pytest.raises(ValidationError):
        storage.create_submission(assignment.id, student.id, "not-a-status")

    draft = storage.update_submission_status(submission.id, SubmissionStatus.DRAFT)
    assert draft.status is SubmissionStatus.DRAFT
    assert draft.submitted_at is None

    submitted = storage.update_submission_status(
        submission.id, SubmissionStatus.SUBMITTED
    )
    assert submitted.submitted_at is not None

    storage.record_correction(submission.id, 5.0, 10.0)
    with pytest.raises(ConflictError):
        storage.update_submission_status(submission.id, SubmissionStatus.SUBMITTED)
    with pytest.raises(ValidationError):
        storage.update_submission_status(submission.id, SubmissionStatus.GRADED)


def test_cascade_delete_removes_submissions_and_results(storage):
    student = make_student(storage)
    assignment = make_assignment(storage)
    submission = storage.create_submission(
        assignment.id, student.id, SubmissionStatus.SUBMITTED
    )
    storage.record_correction(submission.id, 0.0, 10.0)

    with storage.database.connection() as conn:
        conn.execute("DELETE FROM students WHERE id = ?", (student.id,))

    assert storage.get_submission(submission.id) is None
    assert storage.get_correction_for_submission(submission.id) is None


def test_settings_defaults_update_and_validation(storage, caplog):
    assert storage.get_settings() == {
        "max_upload_mb": 25,
        "default_feedback_detail": "detailed",
    }

    updated = storage.update_settings(
        {"max_upload_mb": 10, "default_feedback_detail": "brief"}
    )
    assert updated == {
        "max_upload_mb": 10,
        "default_feedback_detail": "brief",
    }
    assert storage.get_settings() == updated

    invalid_updates = (
        {},
        {"unknown": 1},
        {"max_upload_mb": 0},
        {"max_upload_mb": 26},
        {"max_upload_mb": "10"},
        {"max_upload_mb": True},
        {"default_feedback_detail": "verbose"},
    )
    for changes in invalid_updates:
        with pytest.raises(SettingsValidationError):
            storage.update_settings(changes)
    assert storage.get_settings() == updated

    # A corrupt stored value must fall back safely instead of breaking reads.
    with storage.database.connection() as conn:
        conn.execute(
            "UPDATE settings SET value = 'not-a-number' WHERE key = 'max_upload_mb'"
        )
    with caplog.at_level(logging.WARNING, logger="mathchecker.storage"):
        fallback = storage.get_settings()
    assert fallback["max_upload_mb"] == 25
    assert "max_upload_mb" in caplog.text
    assert "not-a-number" not in caplog.text


def test_stats_count_every_submission_state_and_outcome(storage):
    first = make_student(storage, "First")
    second = make_student(storage, "Second")
    missing_assignment = make_assignment(storage, "Missing", "CH1L1")
    draft_assignment = make_assignment(storage, "Draft", "CH1L2")
    submitted_assignment = make_assignment(storage, "Submitted", "CH1L3")
    graded_assignment = make_assignment(storage, "Graded", "CH1L4")
    failed_assignment = make_assignment(storage, "Failed", "CH1L5")

    storage.create_submission(
        missing_assignment.id, first.id, SubmissionStatus.MISSING
    )
    storage.create_submission(draft_assignment.id, first.id, SubmissionStatus.DRAFT)
    storage.create_submission(
        submitted_assignment.id, first.id, SubmissionStatus.SUBMITTED
    )
    graded = storage.create_submission(
        graded_assignment.id, second.id, SubmissionStatus.SUBMITTED
    )
    failed = storage.create_submission(
        failed_assignment.id, second.id, SubmissionStatus.SUBMITTED
    )

    storage.record_correction(graded.id, 0.0, 10.0)
    storage.record_correction(
        failed.id,
        None,
        None,
        outcome=CorrectionOutcome.FAILED,
        error="Provider failed.",
    )

    stats = storage.stats()
    assert stats.students == 2
    assert stats.assignments == 5
    assert stats.submissions.total == 5
    assert stats.submissions.as_dict() == {
        "total": 5,
        "missing": 1,
        "draft": 1,
        "submitted": 1,
        "graded": 1,
        "failed": 1,
    }
    assert stats.correction_results == 2
    assert stats.completed_results == 1
    assert stats.failed_results == 1
    assert stats.schema_version == 3
