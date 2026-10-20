"""Tests for the explicit development fixture seed."""

from __future__ import annotations

import pytest

from app.db import Database
from app.dev_fixtures import seed_development_data
from app.models import CorrectionOutcome, SubmissionStatus
from app.storage import Storage


@pytest.fixture()
def storage(tmp_path):
    database = Database(tmp_path / "app.db")
    database.initialize()
    return Storage(database)


def test_seed_is_idempotent_and_covers_the_required_states(storage):
    first = seed_development_data(storage)
    assert first == {
        "students_created": 2,
        "assignments_created": 2,
        "submissions_created": 4,
        "corrections_created": 1,
    }

    second = seed_development_data(storage)
    assert second == {
        "students_created": 0,
        "assignments_created": 0,
        "submissions_created": 0,
        "corrections_created": 0,
    }

    assignments = storage.list_assignments()
    assert {assignment.lesson_code for assignment in assignments} == {"CH1L1", "CH1L13"}

    statuses = {submission.status for submission in storage.list_submissions()}
    assert statuses == {
        SubmissionStatus.MISSING,
        SubmissionStatus.DRAFT,
        SubmissionStatus.SUBMITTED,
        SubmissionStatus.GRADED,
    }

    graded = [
        result
        for submission in storage.list_submissions()
        if (result := storage.get_correction_for_submission(submission.id)) is not None
    ]
    assert len(graded) == 1
    assert graded[0].outcome is CorrectionOutcome.COMPLETED
    assert graded[0].awarded == 0.0
    assert graded[0].awarded is not None

    stats = storage.stats()
    assert stats.students == 2
    assert stats.assignments == 2
    assert stats.submissions.total == 4
    assert stats.completed_results == 1
