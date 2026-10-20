"""Tests for the correction-engine contract and its construction point.

These pin the promises the rest of the application depends on: the input
policy has one owner, the factory is honest when unconfigured, a configured
provider produces a real engine (without making a network call here), and the
documented limits match the code.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from pathlib import Path

import pytest

from app.engine import (
    ACCEPTED_MEDIA_TYPES,
    MAX_FILE_BYTES,
    MAX_FILES,
    AssignmentContext,
    CorrectionEngine,
    CorrectionOptions,
    CorrectionRequest,
    EngineError,
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
    path.write_bytes(b"%PDF-1.4\n" + b"x" * size)
    return SubmissionFile(path=path, filename=name, media_type=media_type, size_bytes=size)


def make_request(tmp_path: Path, **file_kwargs) -> CorrectionRequest:
    return CorrectionRequest(
        files=(make_file(tmp_path, **file_kwargs),),
        assignment=AssignmentContext(title="Algebra worksheet 3", mark_scheme="1(a)  2"),
        options=CorrectionOptions(),
    )


def test_get_engine_without_a_key_is_honestly_unavailable() -> None:
    engine = get_engine()
    assert isinstance(engine, CorrectionEngine)
    assert isinstance(engine, UnavailableEngine)
    info = engine.describe()
    assert isinstance(info, EngineInfo)
    assert info.available is False
    assert "API key" in (info.reason or "")


def test_a_configured_key_builds_the_real_engine_without_calling_it(monkeypatch) -> None:
    monkeypatch.setenv("MC6_AI_API_KEY", "test-key-not-a-secret")
    engine = get_engine()
    info = engine.describe()
    assert info.available is True
    assert info.name.startswith("gemini:")
    assert info.reason is None
    for method in ("describe", "submit", "get_job", "get_report"):
        assert callable(getattr(engine, method))


def test_invalid_provider_configuration_is_reported_not_crashed(monkeypatch, caplog) -> None:
    monkeypatch.setenv("MC6_AI_API_KEY", "test-key")
    monkeypatch.setenv("MC6_AI_TIMEOUT_SECONDS", "soon")
    with caplog.at_level(logging.ERROR, logger="mathchecker"):
        engine = get_engine()
    info = engine.describe()
    assert info.available is False
    assert "configuration is invalid" in (info.reason or "")
    assert "test-key" not in (info.reason or "")
    assert "MC6_" not in (info.reason or "")
    # Operators get the variable name in the log; the key value never appears.
    assert "MC6_AI_TIMEOUT_SECONDS" in caplog.text
    assert "test-key" not in caplog.text


def test_unavailable_engine_refuses_instead_of_inventing_results(tmp_path: Path) -> None:
    engine = UnavailableEngine()
    with pytest.raises(EngineUnavailableError):
        asyncio.run(engine.submit(make_request(tmp_path)))
    for coro in (engine.get_job("job-1"), engine.get_report("job-1")):
        with pytest.raises(EngineUnavailableError):
            asyncio.run(coro)


def test_unavailable_messages_are_user_safe() -> None:
    with pytest.raises(EngineUnavailableError) as excinfo:
        asyncio.run(UnavailableEngine().get_job("x"))
    message = str(excinfo.value)
    assert "API key" in message
    assert "MC6_" not in message
    assert "/" not in message and "\\" not in message  # no filesystem paths


def test_validate_request_accepts_supported_input(tmp_path: Path) -> None:
    validate_request(make_request(tmp_path))  # must not raise


def test_validate_request_accepts_a_mark_scheme_file_instead_of_text(tmp_path: Path) -> None:
    submission = make_file(tmp_path, "work.pdf")
    scheme = make_file(tmp_path, "scheme.pdf")
    request = CorrectionRequest(
        files=(submission,),
        assignment=AssignmentContext(title="Worksheet"),
        mark_scheme_files=(scheme,),
    )
    validate_request(request)  # must not raise


def test_validate_request_rejects_unsupported_media_type(tmp_path: Path) -> None:
    request = make_request(tmp_path, name="notes.txt", media_type="text/plain")
    with pytest.raises(UnsupportedInputError):
        validate_request(request)


def test_validate_request_rejects_empty_submission(tmp_path: Path) -> None:
    request = CorrectionRequest(
        files=(),
        assignment=AssignmentContext(title="Nothing attached", mark_scheme="1 1"),
    )
    with pytest.raises(UnsupportedInputError):
        validate_request(request)


def test_validate_request_requires_a_mark_scheme(tmp_path: Path) -> None:
    request = CorrectionRequest(
        files=(make_file(tmp_path),),
        assignment=AssignmentContext(title="No scheme"),
    )
    with pytest.raises(UnsupportedInputError, match="mark scheme is required"):
        validate_request(request)


def test_validate_request_requires_an_assignment_title(tmp_path: Path) -> None:
    request = CorrectionRequest(
        files=(make_file(tmp_path),),
        assignment=AssignmentContext(title="  ", mark_scheme="1 1"),
    )
    with pytest.raises(UnsupportedInputError, match="title"):
        validate_request(request)


def test_validate_request_enforces_the_size_boundary(tmp_path: Path) -> None:
    validate_request(make_request(tmp_path, size=MAX_FILE_BYTES))  # at the limit: fine
    with pytest.raises(UnsupportedInputError):
        validate_request(make_request(tmp_path, size=MAX_FILE_BYTES + 1))
    with pytest.raises(UnsupportedInputError):
        validate_request(make_request(tmp_path, size=0))


def test_validate_request_rejects_invalid_options(tmp_path: Path) -> None:
    request = make_request(tmp_path)
    bad_detail = replace(
        request, options=CorrectionOptions(feedback_detail="essay")
    )
    with pytest.raises(UnsupportedInputError, match="Feedback detail"):
        validate_request(bad_detail)

    for value in (0, -1, float("nan"), True):
        bad_total = replace(request, options=CorrectionOptions(max_score=value))
        with pytest.raises(UnsupportedInputError, match="positive number"):
            validate_request(bad_total)


def test_validate_request_bounds_the_number_of_files(tmp_path: Path) -> None:
    files = tuple(make_file(tmp_path, f"p{index}.pdf") for index in range(MAX_FILES + 1))
    request = CorrectionRequest(
        files=files,
        assignment=AssignmentContext(title="Too many", mark_scheme="1 1"),
    )
    with pytest.raises(UnsupportedInputError, match="Too many files"):
        validate_request(request)


def test_input_policy_matches_the_documented_contract() -> None:
    # docs/correction-engine-contract.md and frontend/js/pages/correction.js
    # state these exact limits; if this test fails, the contract has drifted.
    assert MAX_FILE_BYTES == 25 * 1024 * 1024
    assert ACCEPTED_MEDIA_TYPES == ("application/pdf", "image/png", "image/jpeg")
    assert MAX_FILES == 12


def test_error_types_exist_for_every_documented_failure() -> None:
    # The HTTP mapping in docs/correction-engine-contract.md names these classes.
    for error in (EngineUnavailableError, UnsupportedInputError, JobNotFoundError):
        assert issubclass(error, EngineError)
