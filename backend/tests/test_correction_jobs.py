"""Phase 4 correction-job service tests.

These exercise the durable lifecycle with a deterministic engine. The API /
real-engine integration over a local provider stub lives in
``test_api_corrections.py``; these tests focus on persistence, transitions,
cleanup and failure safety.
"""

from __future__ import annotations

import asyncio
import io
import threading
import time
from pathlib import Path

import pytest

from app.correction.jobs import (
    CorrectionJobService,
    IncomingUpload,
    JobEngineUnavailable,
    JobInputError,
    ReportNotReady,
)
from app.db import Database
from app.engine import (
    CorrectionJob,
    CorrectionReport,
    EngineInfo,
    JobStatus,
    MarkedItem,
)
from app.models import CorrectionJobFile, utc_now
from app.storage import ConflictError, Storage, StorageError

FIXTURES = Path(__file__).parent / "fixtures" / "v5"


class ScriptedEngine:
    """A deterministic engine protocol implementation for lifecycle tests."""

    def __init__(self, *, fail: bool = False, gate: threading.Event | None = None):
        self.name = "fixture:job-engine"
        self.fail = fail
        self.gate = gate
        self.started = threading.Event()
        self.requests = []
        self.reports: dict[str, CorrectionReport] = {}

    def describe(self) -> EngineInfo:
        return EngineInfo(name=self.name, available=True)

    async def submit(self, request):
        self.requests.append(request)
        if self.gate is not None:
            self.started.set()
            while not self.gate.is_set():
                await asyncio.sleep(0.005)
        if self.fail:
            return CorrectionJob(
                job_id=request.job_id,
                status=JobStatus.FAILED,
                submitted_at=utc_now(),
                files=tuple(item.filename for item in request.files),
                error="The AI provider is rate-limiting requests. Try again shortly.",
            )
        report = self._report(request.job_id)
        self.reports[request.job_id] = report
        return CorrectionJob(
            job_id=request.job_id,
            status=JobStatus.COMPLETED,
            submitted_at=utc_now(),
            files=tuple(item.filename for item in request.files),
        )

    async def get_report(self, job_id: str):
        return self.reports[job_id]

    async def get_job(self, job_id: str):
        raise AssertionError("the job service does not call engine.get_job")

    def _report(self, job_id: str) -> CorrectionReport:
        items = (
            MarkedItem("1", 3, 3, "Correct."),
            MarkedItem("2", 2, 2, "Correct."),
            MarkedItem("3", 2, 3, "Method correct; final value wrong."),
            MarkedItem("4", 2, 2, "Correct."),
        )
        return CorrectionReport(
            job_id=job_id,
            summary="Fixture report.",
            awarded=9,
            out_of=10,
            items=items,
            status="completed",
            percentage=90,
            review_required=False,
            unresolved=(),
            engine=self.name,
            created_at=utc_now(),
        )


@pytest.fixture()
def storage(tmp_path):
    database = Database(tmp_path / "app.db")
    database.initialize()
    return Storage(database)


def uploads(name: str = "student_submission.pdf") -> list[IncomingUpload]:
    return [
        IncomingUpload(
            filename=name,
            media_type="application/pdf",
            stream=io.BytesIO((FIXTURES / name).read_bytes()),
        )
    ]


def job_service(storage, engine, tmp_path) -> CorrectionJobService:
    return CorrectionJobService(storage, engine, tmp_path / "uploads")


def create(service: CorrectionJobService, **overrides):
    values = {
        "assignment_title": "Fixture quiz",
        "submission_uploads": uploads("student_submission.pdf"),
        "scheme_uploads": uploads("mark_scheme.pdf"),
    }
    values.update(overrides)
    return service.create_job(**values)


def wait_for_workspace_removed(service, job_id: str, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while (service._root / job_id).exists():
        if time.monotonic() > deadline:
            raise AssertionError("the job workspace was not cleaned up")
        time.sleep(0.01)


def test_job_moves_queued_to_processing_to_completed_and_persists_report(
    storage, tmp_path
):
    gate = threading.Event()
    engine = ScriptedEngine(gate=gate)
    service = job_service(storage, engine, tmp_path)

    queued = create(service)
    assert queued.job_id
    assert queued.status is JobStatus.QUEUED
    files_by_role = {item.role: item.filename for item in queued.files}
    assert files_by_role == {
        "submission": "student_submission.pdf",
        "mark_scheme": "mark_scheme.pdf",
    }

    assert engine.started.wait(2), "the worker did not start"
    processing = storage.get_correction_job(queued.job_id)
    assert processing.status is JobStatus.PROCESSING
    assert processing.started_at is not None

    gate.set()
    done = service.wait_for_terminal(queued.job_id)
    assert done.status is JobStatus.COMPLETED, done.error
    assert done.report_status == "completed"
    assert (done.awarded, done.out_of, done.percentage) == (9.0, 10.0, 90.0)

    report = service.get_report(queued.job_id)
    assert [item.label for item in report.items] == ["1", "2", "3", "4"]
    assert report.awarded == 9
    assert report.out_of == 10
    assert report.percentage == 90
    assert engine.requests[0].job_id == queued.job_id

    wait_for_workspace_removed(service, queued.job_id)
    stored = storage.get_correction_job(queued.job_id)
    assert {item.role: item.filename for item in stored.files}["submission"] == (
        "student_submission.pdf"
    )


def test_provider_failure_is_a_failed_job_not_a_completed_report(storage, tmp_path):
    engine = ScriptedEngine(fail=True)
    service = job_service(storage, engine, tmp_path)
    queued = create(service)

    done = service.wait_for_terminal(queued.job_id)
    assert done.status is JobStatus.FAILED
    assert "rate-limiting" in (done.error or "")
    assert done.report_status is None

    with pytest.raises(ReportNotReady, match="not completed"):
        service.get_report(queued.job_id)
    wait_for_workspace_removed(service, queued.job_id)


def test_corrupt_upload_is_rejected_before_a_job_row_or_engine_call(storage, tmp_path):
    engine = ScriptedEngine()
    service = job_service(storage, engine, tmp_path)
    corrupt = IncomingUpload(
        filename="broken.pdf",
        media_type="application/pdf",
        stream=io.BytesIO(b"%PDF-1.7 not a usable document"),
    )

    with pytest.raises(JobInputError):
        service.create_job(
            assignment_title="Broken",
            submission_uploads=[corrupt],
            mark_scheme_text="1  1",
        )

    assert storage.list_correction_jobs() == []
    assert engine.requests == []
    assert list((tmp_path / "uploads").iterdir()) == []


def test_idempotency_key_reuses_the_existing_job_without_duplicate_work(storage, tmp_path):
    engine = ScriptedEngine()
    service = job_service(storage, engine, tmp_path)

    first = create(service, idempotency_key="request-key-0001")
    service.wait_for_terminal(first.job_id)
    second = create(service, idempotency_key="request-key-0001")

    assert second.job_id == first.job_id
    assert len(storage.list_correction_jobs()) == 1
    assert len(engine.requests) == 1
    assert list((tmp_path / "uploads").iterdir()) == []


def test_idempotency_is_checked_before_invalid_uploads_are_read(storage, tmp_path):
    engine = ScriptedEngine()
    service = job_service(storage, engine, tmp_path)
    first = create(service, idempotency_key="request-key-0002")
    service.wait_for_terminal(first.job_id)

    reused = service.create_job(
        assignment_title="Different title",
        submission_uploads=[],
        mark_scheme_text="",
        idempotency_key="request-key-0002",
    )
    assert reused.job_id == first.job_id


def test_restart_recovery_fails_interrupted_jobs_and_cleans_workspace(storage, tmp_path):
    engine = ScriptedEngine()
    service = job_service(storage, engine, tmp_path)
    record = storage.create_correction_job(
        job_id="job-interrupted-0001",
        assignment_title="Interrupted",
        mark_scheme_text="1  1",
        files=[
            CorrectionJobFile(
                role="submission",
                position=0,
                filename="work.pdf",
                media_type="application/pdf",
                size_bytes=10,
            )
        ],
    )
    # Simulate a job left active by a previous process.
    storage.mark_correction_job_processing(record.job_id)
    workspace = tmp_path / "uploads" / record.job_id
    workspace.mkdir()
    (workspace / "partial.bin").write_bytes(b"x")

    recovered = service.recover_interrupted()
    assert recovered == 1
    recovered_job = storage.get_correction_job(record.job_id)
    assert recovered_job.status is JobStatus.FAILED
    assert "interrupted" in (recovered_job.error or "").lower()
    assert not workspace.exists()


def test_completed_jobs_survive_recovery(storage, tmp_path):
    engine = ScriptedEngine()
    service = job_service(storage, engine, tmp_path)
    record = create(service, idempotency_key="request-key-0004")
    service.wait_for_terminal(record.job_id)

    assert service.recover_interrupted() == 0
    assert storage.get_correction_job(record.job_id).status is JobStatus.COMPLETED
    assert service.get_report(record.job_id).awarded == 9


def test_storage_rejects_a_report_whose_total_contradicts_its_items(storage):
    record = storage.create_correction_job(
        job_id="job-consistency-0001",
        assignment_title="Consistency",
        mark_scheme_text="1  1",
        files=[
            # A metadata-only row is enough for the storage boundary; the
            # workspace and extraction are the job service's concern.
            CorrectionJobFile(
                role="submission",
                position=0,
                filename="work.pdf",
                media_type="application/pdf",
                size_bytes=10,
            )
        ],
    )
    storage.mark_correction_job_processing(record.job_id)
    bad = CorrectionReport(
        job_id=record.job_id,
        summary="Wrong total.",
        awarded=99,
        out_of=1,
        items=(MarkedItem("1", 1, 1, "Correct."),),
        status="completed",
        percentage=100,
    )

    with pytest.raises(StorageError, match="total"):
        storage.complete_correction_job(record.job_id, bad)

    assert storage.get_correction_job(record.job_id).status is JobStatus.PROCESSING
    assert storage.get_correction_report(record.job_id) is None


def test_fractional_marks_persist_with_consistent_totals(storage):
    """Fractional marks (0.5-mark scheme steps) survive the storage boundary
    and reconstruct with totals that agree with their question rows."""
    record = storage.create_correction_job(
        job_id="job-fractional-0001",
        assignment_title="Fractions",
        mark_scheme_text="1 1",
        files=[
            CorrectionJobFile(
                role="submission", position=0, filename="work.pdf",
                media_type="application/pdf", size_bytes=10,
            )
        ],
    )
    storage.mark_correction_job_processing(record.job_id)
    report = CorrectionReport(
        job_id=record.job_id,
        summary="Half-mark scheme",
        awarded=0.75,   # 0.50 + 0.25
        out_of=4.0,     # 1.50 + 2.50
        items=(
            MarkedItem("1", 0.5, 1.5, "Half correct."),
            MarkedItem("2", 0.25, 2.5, "Quarter correct."),
        ),
        status="completed",
        # round(0.75/4*100, 2) = 18.75
        percentage=18.75,
    )
    storage.complete_correction_job(record.job_id, report)

    restored = storage.get_correction_report(record.job_id)
    assert restored is not None
    assert abs(restored.awarded - 0.75) < 1e-9
    assert abs(restored.out_of - 4.0) < 1e-9
    assert abs(restored.percentage - 18.75) < 1e-9
    assert [item.awarded for item in restored.items] == [0.5, 0.25]

    # A completed job is immutable: no state may move it backwards, and a
    # second identical completion is idempotent rather than duplicating rows.
    with pytest.raises(ConflictError):
        storage.mark_correction_job_processing(record.job_id)
    storage.complete_correction_job(record.job_id, report)
    assert len(storage.get_correction_report(record.job_id).items) == 2


def test_unavailable_engine_rejects_creation_before_writing(storage, tmp_path):
    class Unavailable:
        def describe(self):
            return EngineInfo("unavailable", False, "No AI provider is configured.")

    service = CorrectionJobService(storage, Unavailable(), tmp_path / "uploads")
    with pytest.raises(JobEngineUnavailable, match="No AI provider"):
        create(service)
    assert storage.list_correction_jobs() == []
    assert list((tmp_path / "uploads").iterdir()) == []
