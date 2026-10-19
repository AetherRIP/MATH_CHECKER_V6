"""End-to-end check over the bundled V5 reference fixture.

The PDFs in ``fixtures/v5/`` are the authentic synthetic student script and
mark scheme used by V5 (questions 1–4: 3 + 2 + 3 + 2 = 10 marks; reference marks
3 + 2 + 2 + 2 = 9 because question 3 ends with n = 13.33 instead of 14).

The provider response below replays those reference marks. This verifies the
real documents, extraction, blueprint, validation and totals through the
engine; it does NOT evaluate whether a live model would award those marks.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.correction.service import CorrectionService
from app.engine import (
    AssignmentContext,
    CorrectionOptions,
    CorrectionRequest,
    CorrectionReport,
    JobStatus,
    SubmissionFile,
)

FIXTURES = Path(__file__).parent / "fixtures" / "v5"


class ReferenceClient:
    name = "fixture:reference-marks"

    def __init__(self) -> None:
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        return json.dumps(
            {
                "summary": "Reference marks replayed for the bundled V5 fixture.",
                "questions": [
                    {
                        "label": "1",
                        "status": "marked",
                        "awarded": 3,
                        "out_of": 3,
                        "student_answer": "x = 6",
                        "scheme_answer": "x = 6",
                        "feedback": "Correct solution.",
                    },
                    {
                        "label": "2",
                        "status": "marked",
                        "awarded": 2,
                        "out_of": 2,
                        "student_answer": "9/25",
                        "scheme_answer": "9/25",
                        "feedback": "Correct simplification.",
                    },
                    {
                        "label": "3",
                        "status": "marked",
                        "awarded": 2,
                        "out_of": 3,
                        "student_answer": "n = 13.33",
                        "scheme_answer": "n = 14",
                        "feedback": "Method correct; final value wrong.",
                    },
                    {
                        "label": "4",
                        "status": "marked",
                        "awarded": 2,
                        "out_of": 2,
                        "student_answer": "64",
                        "scheme_answer": "64",
                        "feedback": "Correct.",
                    },
                ],
                "warnings": [],
            }
        )


def file_of(name: str) -> SubmissionFile:
    path = FIXTURES / name
    return SubmissionFile(
        path=path,
        filename=name,
        media_type="application/pdf",
        size_bytes=path.stat().st_size,
    )


def test_reference_fixture_runs_through_the_real_pipeline() -> None:
    client = ReferenceClient()
    engine = CorrectionService(client=client)
    request = CorrectionRequest(
        files=(file_of("student_submission.pdf"),),
        assignment=AssignmentContext(
            title="V5 fixture quiz",
            instructions="Show all working.",
            mark_scheme="",
        ),
        options=CorrectionOptions(),
        mark_scheme_files=(file_of("mark_scheme.pdf"),),
    )

    job = asyncio.run(engine.submit(request))

    assert job.status is JobStatus.COMPLETED, job.error
    report = asyncio.run(engine.get_report(job.job_id))
    assert isinstance(report, CorrectionReport)
    assert [(item.label, item.awarded, item.out_of) for item in report.items] == [
        ("1", 3.0, 3.0),
        ("2", 2.0, 2.0),
        ("3", 2.0, 3.0),
        ("4", 2.0, 2.0),
    ]
    assert report.awarded == 9
    assert report.out_of == 10
    assert report.percentage == 90
    assert report.status == "completed"

    # The real mark-scheme document supplied the maximum for every question.
    prompt = client.requests[0].user_prompt
    assert "1: 3 marks" in prompt
    assert "3: 3 marks" in prompt
    assert "Question blueprint extracted from the mark scheme" in prompt
