"""Deterministic development fixtures.

Run explicitly with ``PYTHONPATH=backend python -m app.dev_fixtures`` (or set
``MC6_DATA_DIR`` first). Nothing here runs automatically at startup, and the
data is never committed as production data.

The fixture set deliberately covers the storage rules Phase 2 must prove:

* lesson codes ``CH1L1`` and ``CH1L13`` are preserved exactly;
* missing, draft, submitted and graded submissions are distinct;
* a completed correction may award zero marks.
"""

from __future__ import annotations

from typing import Any

from .models import CorrectionOutcome, SubmissionStatus
from .storage import Storage

SEED_STUDENTS = (
    {
        "id": "seed-student-ada",
        "display_name": "Ada Lovelace",
        "email": "ada@example.test",
        "external_id": "seed-ada",
        "created_at": "2026-09-20T08:00:00+00:00",
    },
    {
        "id": "seed-student-grace",
        "display_name": "Grace Hopper",
        "email": "grace@example.test",
        "external_id": "seed-grace",
        "created_at": "2026-09-20T08:00:00+00:00",
    },
)

SEED_ASSIGNMENTS = (
    {
        "id": "seed-assignment-ch1l1",
        "title": "Chapter 1, Lesson 1 - Number",
        "qualification": "Edexcel IGCSE Mathematics",
        "component": "Paper 1H",
        "lesson_code": "CH1L1",
        "notes": "Development fixture only.",
        "max_score": 10,
        "created_at": "2026-09-21T08:00:00+00:00",
    },
    {
        "id": "seed-assignment-ch1l13",
        "title": "Chapter 1, Lesson 13 - Algebra",
        "qualification": "Edexcel IGCSE Mathematics",
        "component": "Paper 1H",
        "lesson_code": "CH1L13",
        "notes": "Development fixture only.",
        "max_score": 20,
        "created_at": "2026-09-21T08:05:00+00:00",
    },
)

SEED_SUBMISSIONS = (
    {
        "id": "seed-submission-ada-ch1l1",
        "assignment_id": "seed-assignment-ch1l1",
        "student_id": "seed-student-ada",
        "status": SubmissionStatus.SUBMITTED,
        "original_filename": "ada-ch1l1.pdf",
        "media_type": "application/pdf",
        "size_bytes": 1024,
        "submitted_at": "2026-10-01T09:00:00+00:00",
        "created_at": "2026-10-01T09:00:00+00:00",
        "correction": None,
    },
    {
        "id": "seed-submission-grace-ch1l1",
        "assignment_id": "seed-assignment-ch1l1",
        "student_id": "seed-student-grace",
        "status": SubmissionStatus.DRAFT,
        "original_filename": "grace-ch1l1.png",
        "media_type": "image/png",
        "size_bytes": 2048,
        "submitted_at": None,
        "created_at": "2026-10-01T09:05:00+00:00",
        "correction": None,
    },
    {
        "id": "seed-submission-ada-ch1l13",
        "assignment_id": "seed-assignment-ch1l13",
        "student_id": "seed-student-ada",
        "status": SubmissionStatus.MISSING,
        "original_filename": None,
        "media_type": None,
        "size_bytes": None,
        "submitted_at": None,
        "created_at": "2026-10-02T09:00:00+00:00",
        "correction": None,
    },
    {
        "id": "seed-submission-grace-ch1l13",
        "assignment_id": "seed-assignment-ch1l13",
        "student_id": "seed-student-grace",
        "status": SubmissionStatus.SUBMITTED,
        "original_filename": "grace-ch1l13.pdf",
        "media_type": "application/pdf",
        "size_bytes": 4096,
        "submitted_at": "2026-10-02T10:00:00+00:00",
        "created_at": "2026-10-02T10:00:00+00:00",
        "correction": {
            "awarded": 0.0,
            "out_of": 20.0,
            "outcome": CorrectionOutcome.COMPLETED,
            "summary": "Seed result: completed with zero marks.",
            "feedback": "Seed feedback only; no AI correction was run.",
            "created_at": "2026-10-05T12:00:00+00:00",
        },
    },
)


def seed_development_data(storage: Storage) -> dict[str, int]:
    """Insert the fixture set once and return per-entity creation counts.

    Re-running is safe: existing records are left untouched and only genuinely
    missing records are created.
    """
    created = {
        "students_created": 0,
        "assignments_created": 0,
        "submissions_created": 0,
        "corrections_created": 0,
    }

    for spec in SEED_STUDENTS:
        if storage.get_student(spec["id"]) is None:
            storage.create_student(
                spec["display_name"],
                email=spec["email"],
                external_id=spec["external_id"],
                student_id=spec["id"],
                created_at=spec["created_at"],
            )
            created["students_created"] += 1

    for spec in SEED_ASSIGNMENTS:
        if storage.get_assignment(spec["id"]) is None:
            storage.create_assignment(
                spec["title"],
                qualification=spec["qualification"],
                component=spec["component"],
                lesson_code=spec["lesson_code"],
                notes=spec["notes"],
                max_score=spec["max_score"],
                assignment_id=spec["id"],
                created_at=spec["created_at"],
            )
            created["assignments_created"] += 1

    for spec in SEED_SUBMISSIONS:
        submission = storage.get_submission_for(
            spec["assignment_id"], spec["student_id"]
        )
        if submission is None:
            submission = storage.create_submission(
                spec["assignment_id"],
                spec["student_id"],
                spec["status"],
                original_filename=spec["original_filename"],
                media_type=spec["media_type"],
                size_bytes=spec["size_bytes"],
                submitted_at=spec["submitted_at"],
                submission_id=spec["id"],
                created_at=spec["created_at"],
            )
            created["submissions_created"] += 1

        correction: dict[str, Any] | None = spec["correction"]
        if correction is None:
            continue
        if submission.status in (SubmissionStatus.MISSING, SubmissionStatus.DRAFT):
            continue
        if storage.get_correction_for_submission(submission.id) is not None:
            continue
        storage.record_correction(
            submission.id,
            correction["awarded"],
            correction["out_of"],
            outcome=correction["outcome"],
            summary=correction["summary"],
            feedback=correction["feedback"],
            created_at=correction["created_at"],
        )
        created["corrections_created"] += 1

    return created


def main() -> int:
    """Seed the configured development data directory from the command line."""
    from .config import ensure_dirs
    from .db import Database

    config = ensure_dirs()
    database = Database(config.database_path)
    database.initialize()
    result = seed_development_data(Storage(database))
    summary = ", ".join(f"{key}={value}" for key, value in result.items())
    print(f"Development fixtures ready in {config.database_path.name}: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
