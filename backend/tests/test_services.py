"""Tests for the Phase 2 service layer."""

from __future__ import annotations

import logging

import pytest

from app.db import Database, DatabaseUnavailableError
from app.models import SettingsValidationError, SubmissionStatus
from app.services import SettingsService, StatsService
from app.storage import Storage


@pytest.fixture()
def storage(tmp_path):
    database = Database(tmp_path / "app.db")
    database.initialize()
    return Storage(database)


def test_settings_service_updates_and_logs_only_key_names(storage, caplog):
    service = SettingsService(storage)

    with caplog.at_level(logging.INFO, logger="mathchecker.services"):
        updated = service.update({"default_feedback_detail": "brief"})

    assert updated["default_feedback_detail"] == "brief"
    assert "default_feedback_detail" in caplog.text
    assert "brief" not in caplog.text


def test_settings_service_rejects_invalid_updates(storage):
    service = SettingsService(storage)

    for changes in ({}, {"unknown": 1}, {"max_upload_mb": 0}, {"max_upload_mb": 26}):
        with pytest.raises(SettingsValidationError):
            service.update(changes)

    assert service.get() == {
        "max_upload_mb": 25,
        "default_feedback_detail": "detailed",
    }


def test_stats_service_snapshot_shape(storage):
    student = storage.create_student("Ada Lovelace")
    assignment = storage.create_assignment("Chapter 1", lesson_code="CH1L1")
    submission = storage.create_submission(
        assignment.id, student.id, SubmissionStatus.SUBMITTED
    )
    storage.record_correction(submission.id, 0.0, 10.0)

    snapshot = StatsService(storage).snapshot()

    assert snapshot["database"] == {"status": "ready", "schema_version": 1}
    assert snapshot["counts"]["students"] == 1
    assert snapshot["counts"]["assignments"] == 1
    assert snapshot["counts"]["submissions"]["graded"] == 1
    assert snapshot["counts"]["correction_results"] == 1


def test_stats_service_reports_an_uninitialized_database(tmp_path):
    storage = Storage(Database(tmp_path / "not-initialized.db"))
    with pytest.raises(DatabaseUnavailableError):
        StatsService(storage).snapshot()
