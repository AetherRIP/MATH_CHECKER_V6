"""Tests for the Phase 2 correction-engine contract and its Phase 1 stub.

These pin the contract's promises: the stub is honest about being
unavailable, the input policy has exactly one owner, and the documented
limits match the code so the doc cannot drift silently.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.engine import (
    ACCEPTED_MEDIA_TYPES,
    MAX_FILE_BYTES,
    AssignmentContext,
    CorrectionEngine,
    CorrectionOptions,
    CorrectionRequest,
    EngineInfo,
    EngineUnavailableError,
    JobNotFoundError,
    SubmissionFile,
    UnavailableEngine,
    UnsupportedInputError,
    get_engine,
    validate_request,
)


def make_file(
    tmp_path: Path,
    name: str = "homework.pdf",
    media_type: str = "application/pdf",
    size: int = 1024,
) -> SubmissionFile:
    path = tmp_path / name
    path.write_bytes(b"x" * size)
    return SubmissionFile(path=path, filename=name, media_type=media_type, size_bytes=size)


def make_request(tmp_path: Path, **file_kwargs) -> CorrectionRequest:
    return CorrectionRequest(
        files=(make_file(tmp_path, **file_kwargs),),
        assignment=AssignmentContext(title="Algebra worksheet 3"),
        options=CorrectionOptions(),
    )


def test_get_engine_satisfies_the_protocol() -> None:
    engine = get_engine()
    assert isinstance(engine, CorrectionEngine)
    for method in ("describe", "submit", "get_job", "get_report"):
        assert callable(getattr(engine, method))


def test_describe_is_honest_in_phase_1() -> None:
    info = get_engine().describe()
    assert isinstance(info, EngineInfo)
    assert info.available is False
    assert info.name
    assert info.reason and "Phase 2" in info.reason


def test_submit_refuses_instead_of_inventing_results(tmp_path: Path) -> None:
    engine = get_engine()
    with pytest.raises(EngineUnavailableError):
        asyncio.run(engine.submit(make_request(tmp_path)))


def test_job_and_report_lookups_also_refuse(tmp_path: Path) -> None:
    engine = get_engine()
    for coro in (engine.get_job("job-1"), engine.get_report("job-1")):
        with pytest.raises(EngineUnavailableError):
            asyncio.run(coro)


def test_unavailable_messages_are_user_safe() -> None:
    # describe() answers rather than raising, even for the stub.
    assert isinstance(get_engine().describe(), EngineInfo)

    with pytest.raises(EngineUnavailableError) as excinfo:
        asyncio.run(UnavailableEngine().get_job("x"))
    message = str(excinfo.value)
    assert "Phase 2" in message
    assert "/" not in message and "\\" not in message  # no filesystem paths


def test_validate_request_accepts_supported_input(tmp_path: Path) -> None:
    validate_request(make_request(tmp_path))  # must not raise


def test_validate_request_rejects_unsupported_media_type(tmp_path: Path) -> None:
    request = make_request(tmp_path, name="notes.txt", media_type="text/plain")
    with pytest.raises(UnsupportedInputError):
        validate_request(request)


def test_validate_request_rejects_empty_submission(tmp_path: Path) -> None:
    request = CorrectionRequest(
        files=(),
        assignment=AssignmentContext(title="Nothing attached"),
    )
    with pytest.raises(UnsupportedInputError):
        validate_request(request)


def test_validate_request_enforces_the_size_boundary(tmp_path: Path) -> None:
    validate_request(make_request(tmp_path, size=MAX_FILE_BYTES))  # at the limit: fine
    with pytest.raises(UnsupportedInputError):
        validate_request(make_request(tmp_path, size=MAX_FILE_BYTES + 1))
    with pytest.raises(UnsupportedInputError):
        validate_request(make_request(tmp_path, size=0))


def test_input_policy_matches_the_documented_contract() -> None:
    # docs/phase-2-contract.md and frontend/js/pages/correction.js state these
    # exact limits; if this test fails, the contract has drifted.
    assert MAX_FILE_BYTES == 25 * 1024 * 1024
    assert ACCEPTED_MEDIA_TYPES == ("application/pdf", "image/png", "image/jpeg")


def test_error_types_exist_for_every_documented_failure() -> None:
    # The HTTP mapping in docs/phase-2-contract.md names these classes.
    assert issubclass(EngineUnavailableError, Exception)
    assert issubclass(UnsupportedInputError, Exception)
    assert issubclass(JobNotFoundError, Exception)
