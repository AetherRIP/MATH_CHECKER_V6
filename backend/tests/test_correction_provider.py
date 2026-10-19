"""Provider-client tests over a real local HTTP server.

No external provider is contacted. A stub server exercises the real urllib
transport, request shape, status mapping, bounded retries and response
parsing.
"""

from __future__ import annotations

import asyncio
import base64
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app.correction.provider import (
    GeminiClient,
    ModelAttachment,
    ModelRequest,
    ProviderFailure,
)
from app.correction.service import CorrectionService
from app.engine import AssignmentContext, CorrectionRequest, SubmissionFile
from pdf_factory import make_pdf


class StubState:
    def __init__(self):
        self.responses: list[tuple[int, dict]] = []
        self.requests: list[dict] = []


@contextmanager
def stub_server(state: StubState):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - stdlib naming
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            state.requests.append(
                {
                    "path": self.path,
                    "headers": {key.lower(): value for key, value in self.headers.items()},
                    "body": json.loads(body.decode("utf-8")),
                }
            )
            status, payload = state.responses.pop(0)
            data = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):  # silence the test server
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def candidate(text: str, finish: str = "STOP") -> dict:
    return {
        "candidates": [
            {"content": {"parts": [{"text": text}]}, "finishReason": finish}
        ]
    }


def request() -> ModelRequest:
    return ModelRequest(
        system_prompt="system instructions",
        user_prompt="mark this",
        attachments=(
            ModelAttachment(
                filename="work.pdf",
                media_type="application/pdf",
                data=b"%PDF-1.4 test",
            ),
        ),
    )


def test_generate_sends_a_well_formed_request_and_returns_text() -> None:
    state = StubState()
    state.responses = [(200, candidate('{"ok": true}'))]
    with stub_server(state) as url:
        client = GeminiClient(
            api_key="secret-key",
            model="gemini-test",
            base_url=url,
            timeout_seconds=10,
        )
        assert client.generate(request()) == '{"ok": true}'

    sent = state.requests[0]
    assert sent["path"] == "/v1beta/models/gemini-test:generateContent"
    assert sent["headers"]["x-goog-api-key"] == "secret-key"
    assert sent["headers"]["content-type"] == "application/json"
    assert sent["body"]["system_instruction"]["parts"][0]["text"] == "system instructions"
    parts = sent["body"]["contents"][0]["parts"]
    assert parts[0]["inline_data"]["mime_type"] == "application/pdf"
    assert base64.b64decode(parts[0]["inline_data"]["data"]) == b"%PDF-1.4 test"
    assert parts[-1]["text"] == "mark this"
    assert sent["body"]["generationConfig"]["responseMimeType"] == "application/json"


def test_transient_failure_is_retried_then_succeeds() -> None:
    state = StubState()
    state.responses = [(503, {"error": "busy"}), (200, candidate('{"ok": true}'))]
    with stub_server(state) as url:
        client = GeminiClient(
            api_key="secret-key",
            model="gemini-test",
            base_url=url,
            max_retries=1,
            sleep=lambda _seconds: None,
        )
        assert client.generate(request()) == '{"ok": true}'

    assert len(state.requests) == 2


def test_rate_limit_exhaustion_reports_a_safe_message() -> None:
    state = StubState()
    state.responses = [(429, {"error": "quota"}), (429, {"error": "quota"})]
    with stub_server(state) as url:
        client = GeminiClient(
            api_key="secret-key",
            model="gemini-test",
            base_url=url,
            max_retries=1,
            sleep=lambda _seconds: None,
        )
        with pytest.raises(ProviderFailure) as excinfo:
            client.generate(request())

    assert "rate-limiting" in str(excinfo.value)
    assert "secret-key" not in str(excinfo.value)
    assert len(state.requests) == 2


def test_authentication_failure_is_not_retried() -> None:
    state = StubState()
    state.responses = [(403, {"error": "denied"})]
    with stub_server(state) as url:
        client = GeminiClient(
            api_key="secret-key",
            model="gemini-test",
            base_url=url,
            max_retries=3,
            sleep=lambda _seconds: None,
        )
        with pytest.raises(ProviderFailure, match="rejected the configured API key"):
            client.generate(request())

    assert len(state.requests) == 1


def test_truncated_output_is_rejected_even_when_text_is_present() -> None:
    state = StubState()
    state.responses = [(200, candidate('{"questions": [', finish="MAX_TOKENS"))]
    with stub_server(state) as url:
        client = GeminiClient(api_key="k", model="m", base_url=url, max_retries=0)
        with pytest.raises(ProviderFailure, match="cut off"):
            client.generate(request())


def test_blocked_and_empty_responses_are_reported() -> None:
    state = StubState()
    state.responses = [
        (200, {"promptFeedback": {"blockReason": "SAFETY"}}),
        (200, {"candidates": []}),
        (200, candidate("")),
    ]
    with stub_server(state) as url:
        client = GeminiClient(api_key="k", model="m", base_url=url, max_retries=0)
        with pytest.raises(ProviderFailure, match="declined"):
            client.generate(request())
        with pytest.raises(ProviderFailure, match="no result"):
            client.generate(request())
        with pytest.raises(ProviderFailure, match="empty response"):
            client.generate(request())


def test_full_engine_pipeline_over_real_provider_transport(tmp_path: Path) -> None:
    """Documents → prompt → HTTP → JSON → validation → report, end to end.

    The provider is a local stub, so this proves the real transport path
    without contacting (or paying) an external service.
    """
    marking = {
        "summary": "One question marked.",
        "questions": [
            {
                "label": "1(a)",
                "status": "marked",
                "awarded": 2,
                "out_of": 2,
                "student_answer": "4",
                "scheme_answer": "4",
                "feedback": "Correct.",
            }
        ],
    }
    state = StubState()
    state.responses = [(200, candidate(json.dumps(marking)))]
    submission = make_pdf(["Question 1(a)\nAnswer: 4"], path=tmp_path / "work.pdf")

    with stub_server(state) as url:
        client = GeminiClient(
            api_key="local-test-key",
            model="gemini-test",
            base_url=url,
            timeout_seconds=10,
            max_retries=0,
        )
        engine = CorrectionService(client=client)
        request = CorrectionRequest(
            files=(
                SubmissionFile(
                    path=submission,
                    filename="work.pdf",
                    media_type="application/pdf",
                    size_bytes=submission.stat().st_size,
                ),
            ),
            assignment=AssignmentContext(
                title="Integration worksheet", mark_scheme="1(a)  2"
            ),
        )
        job = asyncio.run(engine.submit(request))
        report = asyncio.run(engine.get_report(job.job_id))

    assert job.status.value == "completed"
    assert report.awarded == 2
    assert report.out_of == 2
    assert report.percentage == 100.0
    assert state.requests[0]["body"]["contents"][0]["parts"][0]["inline_data"]["mime_type"] == "application/pdf"


def test_non_json_response_body_is_reported() -> None:
    state = StubState()
    state.responses = [(200, b"<html>not json</html>")]
    with stub_server(state) as url:
        client = GeminiClient(api_key="k", model="m", base_url=url, max_retries=0)
        with pytest.raises(ProviderFailure, match="unreadable response"):
            client.generate(request())
