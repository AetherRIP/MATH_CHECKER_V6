"""Engine orchestration tests using a deterministic fake provider.

These tests exercise the real pipeline — document validation, extraction,
blueprint parsing, prompt construction, JSON parsing, result validation,
deterministic checks and the job registry — with only the remote model call
replaced. No paid provider is contacted.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import replace
from pathlib import Path

import pytest

from app.correction.provider import MAX_INLINE_BYTES, ProviderFailure
from app.correction.service import CorrectionService
from app.engine import (
    AssignmentContext,
    CorrectionOptions,
    CorrectionRequest,
    EngineError,
    JobNotFoundError,
    JobStatus,
    SubmissionFile,
    UnsupportedInputError,
)
from pdf_factory import make_pdf

SCHEME_TEXT = "1(a)  2\n1(b)  1"


class FakeClient:
    name = "fake:test-model"

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("FakeClient received more calls than expected")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if isinstance(response, str):
            return response
        return json.dumps(response)


def make_file(path: Path, media_type: str = "application/pdf") -> SubmissionFile:
    return SubmissionFile(
        path=path,
        filename=path.name,
        media_type=media_type,
        size_bytes=path.stat().st_size,
    )


def make_request(tmp_path: Path, *, with_scheme_file: bool = False) -> CorrectionRequest:
    submission = make_pdf(
        ["Question 1(a)\nWork: 2 + 2 = 4\nAnswer: 4", "Question 1(b)\nAnswer: 7"],
        path=tmp_path / "student.pdf",
    )
    scheme_files = ()
    if with_scheme_file:
        scheme_files = (
            make_file(make_pdf([SCHEME_TEXT], path=tmp_path / "scheme.pdf")),
        )
    return CorrectionRequest(
        files=(make_file(submission),),
        assignment=AssignmentContext(
            title="Algebra worksheet 3",
            instructions="Show all working.",
            mark_scheme="" if with_scheme_file else SCHEME_TEXT,
        ),
        options=CorrectionOptions(),
        mark_scheme_files=scheme_files,
    )


def payload(**overrides):
    data = {
        "summary": "Both questions were marked.",
        "questions": [
            {
                "label": "1(a)",
                "status": "marked",
                "awarded": 2,
                "out_of": 2,
                "student_answer": "4",
                "scheme_answer": "4",
                "student_evidence": "2 + 2 = 4",
                "scheme_evidence": "B2 for 4",
                "criteria": [{"code": "B2", "awarded": True, "reason": "correct"}],
                "feedback": "Fully correct.",
                "review_flags": [],
                "warnings": [],
            },
            {
                "label": "1(b)",
                "status": "marked",
                "awarded": 1,
                "out_of": 1,
                "student_answer": "7",
                "scheme_answer": "7",
                "feedback": "Correct.",
            },
        ],
        "warnings": [],
    }
    data.update(overrides)
    return data


def run(coro):
    return asyncio.run(coro)


def test_successful_submit_produces_a_consistent_completed_report(tmp_path: Path) -> None:
    client = FakeClient([payload()])
    engine = CorrectionService(client=client)

    job = run(engine.submit(make_request(tmp_path)))

    assert job.status is JobStatus.COMPLETED
    assert job.job_id
    assert job.files == ("student.pdf",)
    assert job.error is None

    report = run(engine.get_report(job.job_id))
    assert report.status == "completed"
    assert report.awarded == 3
    assert report.out_of == 3
    assert report.percentage == 100.0
    assert [item.label for item in report.items] == ["1(a)", "1(b)"]
    assert report.review_required is False

    assert run(engine.get_job(job.job_id)).status is JobStatus.COMPLETED
    assert engine.describe().name == "fake:test-model"

    # The real PDF was attached for visual interpretation and the extracted
    # text and mark scheme reached the prompt.
    sent = client.requests[0]
    assert len(sent.attachments) == 1
    assert sent.attachments[0].media_type == "application/pdf"
    assert sent.attachments[0].data.startswith(b"%PDF-")
    assert "Algebra worksheet 3" in sent.user_prompt
    assert "1(a)  2" in sent.user_prompt


def test_model_totals_are_ignored_and_recomputed(tmp_path: Path) -> None:
    client = FakeClient([payload(awarded=99, out_of=99, percentage=99)])
    engine = CorrectionService(client=client)

    job = run(engine.submit(make_request(tmp_path)))
    report = run(engine.get_report(job.job_id))

    assert report.awarded == 3
    assert report.out_of == 3
    assert report.percentage == 100.0


def test_a_mark_scheme_file_is_accepted_and_recorded(tmp_path: Path) -> None:
    client = FakeClient([payload()])
    engine = CorrectionService(client=client)

    job = run(engine.submit(make_request(tmp_path, with_scheme_file=True)))
    report = run(engine.get_report(job.job_id))

    assert job.status is JobStatus.COMPLETED
    assert job.files == ("student.pdf", "scheme.pdf")
    assert report.out_of == 3


def test_provider_failure_creates_a_failed_job_not_a_report(tmp_path: Path) -> None:
    client = FakeClient([ProviderFailure("The AI provider is rate-limiting requests. Try again shortly.")])
    engine = CorrectionService(client=client)

    job = run(engine.submit(make_request(tmp_path)))

    assert job.status is JobStatus.FAILED
    assert "rate-limiting" in (job.error or "")
    assert "Traceback" not in (job.error or "")
    with pytest.raises(EngineError, match="has not completed"):
        run(engine.get_report(job.job_id))


def test_invalid_json_gets_one_bounded_repair_attempt(tmp_path: Path) -> None:
    client = FakeClient(["not json at all", payload()])
    engine = CorrectionService(client=client)

    job = run(engine.submit(make_request(tmp_path)))

    assert job.status is JobStatus.COMPLETED
    assert len(client.requests) == 2
    assert client.requests[1].attachments == ()
    assert "could not be parsed" in client.requests[1].user_prompt


def test_invalid_json_twice_fails_honestly(tmp_path: Path) -> None:
    client = FakeClient(["nope", "still nope"])
    engine = CorrectionService(client=client)

    job = run(engine.submit(make_request(tmp_path)))

    assert job.status is JobStatus.FAILED
    assert "not valid JSON" in (job.error or "")
    assert len(client.requests) == 2


def test_impossible_mark_fails_the_job_and_is_not_stored(tmp_path: Path) -> None:
    broken = payload()
    broken["questions"][0]["awarded"] = 3  # maximum is 2
    client = FakeClient([broken])
    engine = CorrectionService(client=client)

    job = run(engine.submit(make_request(tmp_path)))

    assert job.status is JobStatus.FAILED
    assert "maximum" in (job.error or "").lower()
    with pytest.raises(EngineError):
        run(engine.get_report(job.job_id))


def test_corrupt_pdf_fails_before_calling_the_provider(tmp_path: Path) -> None:
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"%PDF-1.7\ngarbage")
    request = CorrectionRequest(
        files=(
            SubmissionFile(
                path=bad,
                filename="broken.pdf",
                media_type="application/pdf",
                size_bytes=bad.stat().st_size,
            ),
        ),
        assignment=AssignmentContext(title="Broken", mark_scheme=SCHEME_TEXT),
    )
    client = FakeClient([])
    engine = CorrectionService(client=client)

    job = run(engine.submit(request))

    assert job.status is JobStatus.FAILED
    assert "could not be opened" in (job.error or "") or "no pages" in (job.error or "")
    assert client.requests == []


def test_unreadable_question_produces_a_partial_report_not_a_zero(tmp_path: Path) -> None:
    partial = payload()
    partial["questions"][1] = {
        "label": "1(b)",
        "status": "unreadable",
        "awarded": None,
        "out_of": 1,
        "review_flags": ["answer_extraction_uncertain"],
        "warnings": ["The handwriting is unclear."],
    }
    client = FakeClient([partial])
    engine = CorrectionService(client=client)

    job = run(engine.submit(make_request(tmp_path)))
    report = run(engine.get_report(job.job_id))

    assert job.status is JobStatus.COMPLETED  # the run finished
    assert report.status == "partial"
    assert report.percentage is None
    assert report.unresolved == ("1(b)",)
    assert report.items[1].awarded is None
    assert report.review_required is True


def test_logs_do_not_contain_student_content_or_paths(tmp_path: Path, caplog) -> None:
    client = FakeClient([payload(summary="PRIVATE_STUDENT_WORK")])
    engine = CorrectionService(client=client)

    with caplog.at_level(logging.INFO, logger="mathchecker"):
        run(engine.submit(make_request(tmp_path)))

    text = caplog.text
    assert "PRIVATE_STUDENT_WORK" not in text
    assert "student.pdf" not in text
    assert str(tmp_path) not in text


def test_expected_total_mismatch_is_reported_for_review(tmp_path: Path) -> None:
    client = FakeClient([payload()])
    engine = CorrectionService(client=client)
    request = replace(make_request(tmp_path), options=CorrectionOptions(max_score=10))

    job = run(engine.submit(request))
    report = run(engine.get_report(job.job_id))

    assert report.out_of == 3
    assert report.review_required is True
    assert any("differs from the expected total" in warning for warning in report.warnings)


def test_request_validation_happens_before_any_provider_call(tmp_path: Path) -> None:
    client = FakeClient([])
    engine = CorrectionService(client=client)
    request = make_request(tmp_path)
    no_scheme = CorrectionRequest(
        files=request.files,
        assignment=AssignmentContext(title="No scheme"),
    )

    with pytest.raises(UnsupportedInputError, match="mark scheme"):
        run(engine.submit(no_scheme))
    assert client.requests == []


def test_unknown_job_raises_not_found() -> None:
    engine = CorrectionService(client=FakeClient([]))
    for coro in (engine.get_job("missing"), engine.get_report("missing")):
        with pytest.raises(JobNotFoundError):
            run(coro)


def test_caller_files_are_not_deleted(tmp_path: Path) -> None:
    client = FakeClient([payload()])
    engine = CorrectionService(client=client)
    request = make_request(tmp_path)

    run(engine.submit(request))

    assert request.files[0].path.exists()
    for item in request.mark_scheme_files:
        assert item.path.exists()


def test_oversized_inline_payload_falls_back_to_extracted_text(tmp_path: Path) -> None:
    client = FakeClient([payload()])
    engine = CorrectionService(client=client, max_inline_bytes=1)

    job = run(engine.submit(make_request(tmp_path)))
    report = run(engine.get_report(job.job_id))

    assert job.status is JobStatus.COMPLETED
    assert client.requests[0].attachments == ()
    assert any("not sent visually" in warning for warning in report.warnings)


def test_untexted_image_that_cannot_be_sent_fails_honestly(tmp_path: Path) -> None:
    image = tmp_path / "page.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    client = FakeClient([])
    engine = CorrectionService(client=client, max_inline_bytes=1)
    request = CorrectionRequest(
        files=(
            SubmissionFile(
                path=image,
                filename="page.png",
                media_type="image/png",
                size_bytes=image.stat().st_size,
            ),
        ),
        assignment=AssignmentContext(title="Image", mark_scheme=SCHEME_TEXT),
    )

    job = run(engine.submit(request))

    assert job.status is JobStatus.FAILED
    assert "no extractable text" in (job.error or "")
    assert client.requests == []


def test_default_inline_budget_is_documented() -> None:
    assert MAX_INLINE_BYTES > 0
