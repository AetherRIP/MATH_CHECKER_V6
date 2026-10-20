"""Tests for the database statistics API."""

from __future__ import annotations

from app.models import SubmissionStatus


def test_empty_database_stats_shape(client, tmp_path):
    response = client.get("/api/database/stats")
    assert response.status_code == 200
    data = response.json()

    assert data["database"] == {"status": "ready", "schema_version": 3}
    assert data["counts"] == {
        "students": 0,
        "assignments": 0,
        "submissions": {
            "total": 0,
            "missing": 0,
            "draft": 0,
            "submitted": 0,
            "graded": 0,
            "failed": 0,
        },
        "correction_results": 0,
        "completed_results": 0,
        "failed_results": 0,
    }
    assert str(tmp_path) not in response.text
    assert "MC6_" not in response.text


def test_stats_reflect_real_records(client):
    storage = client.app.state.storage
    student = storage.create_student("Ada Lovelace")
    assignment = storage.create_assignment("Chapter 1", lesson_code="CH1L13")
    submission = storage.create_submission(
        assignment.id, student.id, SubmissionStatus.SUBMITTED
    )
    storage.record_correction(submission.id, 0.0, 10.0)

    data = client.get("/api/database/stats").json()
    counts = data["counts"]

    assert counts["students"] == 1
    assert counts["assignments"] == 1
    assert counts["submissions"]["total"] == 1
    assert counts["submissions"]["graded"] == 1
    assert counts["correction_results"] == 1
    assert counts["completed_results"] == 1
    assert counts["failed_results"] == 0
