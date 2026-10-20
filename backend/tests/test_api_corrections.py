"""Phase 4 API tests: real job service + real Phase 3 engine over a stub provider.

The provider is a local HTTP server, so the complete path (multipart upload →
workspace → extraction → prompt → HTTP transport → JSON validation →
deterministic checks → SQLite → HTTP result) is exercised without contacting a
paid external service. The API routes themselves are exercised through
Starlette's TestClient.
"""

from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as app_main
from app.models import CorrectionJobFile

FIXTURES = Path(__file__).parent / "fixtures" / "v5"


class StubState:
    def __init__(self):
        self.responses: list[tuple[int, dict | bytes]] = []
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
                    "headers": {
                        key.lower(): value for key, value in self.headers.items()
                    },
                    "body": json.loads(body.decode("utf-8")),
                }
            )
            status, payload = state.responses.pop(0)
            data = (
                payload
                if isinstance(payload, bytes)
                else json.dumps(payload).encode("utf-8")
            )
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
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


MARKING = {
    "summary": "Four questions marked.",
    "questions": [
        {
            "label": "1",
            "status": "marked",
            "awarded": 3,
            "out_of": 3,
            "student_answer": "4",
            "scheme_answer": "4",
            "student_evidence": "2 + 2 = 4",
            "scheme_evidence": "B3 for 4",
            "feedback": "Correct.",
        },
        {
            "label": "2",
            "status": "marked",
            "awarded": 2,
            "out_of": 2,
            "student_answer": "7",
            "scheme_answer": "7",
            "feedback": "Correct.",
        },
        {
            "label": "3",
            "status": "marked",
            "awarded": 2,
            "out_of": 3,
            "student_answer": "5",
            "scheme_answer": "6",
            "student_evidence": "x = 5",
            "scheme_evidence": "M1 A1 A1 for x = 6",
            "feedback": "Method accepted; final value is wrong.",
        },
        {
            "label": "4",
            "status": "marked",
            "awarded": 2,
            "out_of": 2,
            "student_answer": "12",
            "scheme_answer": "12",
            "feedback": "Correct.",
        },
    ],
    "warnings": [],
}


def set_environment(monkeypatch, tmp_path, *, provider_url: str, api_key: str | None):
    monkeypatch.setenv("MC6_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MC6_LOG_LEVEL", "WARNING")
    monkeypatch.delenv("MC6_TMP_DIR", raising=False)
    monkeypatch.setattr("app.config.ENV_FILE", tmp_path / "no-such.env")
    if api_key is None:
        monkeypatch.delenv("MC6_AI_API_KEY", raising=False)
    else:
        monkeypatch.setenv("MC6_AI_API_KEY", api_key)
    monkeypatch.setenv("MC6_AI_BASE_URL", provider_url)
    monkeypatch.setenv("MC6_AI_MODEL", "gemini-test")
    monkeypatch.setenv("MC6_AI_MAX_RETRIES", "0")
    monkeypatch.setenv("MC6_AI_TIMEOUT_SECONDS", "20")


@contextmanager
def client_for(monkeypatch, tmp_path, *, provider_url: str, api_key: str | None = "local-test-key"):
    set_environment(
        monkeypatch, tmp_path, provider_url=provider_url, api_key=api_key
    )
    with TestClient(app_main.app) as client:
        yield client


def uploads(*, include_scheme: bool = True, submission: bytes | None = None):
    files = [
        (
            "files",
            (
                "student_submission.pdf",
                submission
                if submission is not None
                else (FIXTURES / "student_submission.pdf").read_bytes(),
                "application/pdf",
            ),
        )
    ]
    if include_scheme:
        files.append(
            (
                "mark_scheme_files",
                (
                    "mark_scheme.pdf",
                    (FIXTURES / "mark_scheme.pdf").read_bytes(),
                    "application/pdf",
                ),
            )
        )
    return files


def form(**overrides):
    data = {
        "assignment_title": "V5 fixture worksheet",
        "instructions": "Show all working.",
        "feedback_detail": "detailed",
    }
    data.update(overrides)
    return data


def submit(client, *, files=None, data=None, headers=None):
    return client.post(
        "/api/corrections",
        files=files if files is not None else uploads(),
        data=data if data is not None else form(),
        headers=headers or {},
    )


def wait_for_terminal(client, job_id: str, timeout: float = 15.0) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        response = client.get(f"/api/corrections/{job_id}")
        assert response.status_code == 200, response.text
        body = response.json()
        if body["status"] in ("completed", "failed"):
            return body
        if time.monotonic() >= deadline:
            raise AssertionError(f"job {job_id} did not finish: {body}")
        time.sleep(0.025)


def workspace_children(client) -> list[Path]:
    root = client.app.state.jobs._root
    return list(root.iterdir()) if root.exists() else []


def test_complete_workflow_persists_report_and_survives_restart(monkeypatch, tmp_path):
    state = StubState()
    state.responses = [(200, candidate(json.dumps(MARKING)))]
    with stub_server(state) as url:
        with client_for(monkeypatch, tmp_path, provider_url=url) as client:
            response = submit(client)
            assert response.status_code == 202, response.text
            created = response.json()
            assert created["status"] in ("queued", "processing")
            job_id = created["job_id"]
            assert created["files"][0]["role"] == "submission"
            assert created["files"][0]["filename"] == "student_submission.pdf"
            assert created["files"][1]["role"] == "mark_scheme"
            assert "mark_scheme_text" not in response.text
            assert str(tmp_path) not in response.text

            completed = wait_for_terminal(client, job_id)
            assert completed["status"] == "completed", completed
            assert completed["report_status"] == "completed"
            assert (completed["awarded"], completed["out_of"], completed["percentage"]) == (
                9,
                10,
                90,
            )
            assert completed["started_at"]
            assert completed["completed_at"]
            assert completed["error"] is None

            report_response = client.get(f"/api/corrections/{job_id}/report")
            assert report_response.status_code == 200, report_response.text
            report = report_response.json()
            assert report["job_id"] == job_id
            assert report["status"] == "completed"
            assert report["summary"] == "Four questions marked."
            assert (report["awarded"], report["out_of"], report["percentage"]) == (
                9,
                10,
                90,
            )
            assert [item["label"] for item in report["items"]] == ["1", "2", "3", "4"]
            assert [
                (item["awarded"], item["out_of"]) for item in report["items"]
            ] == [(3, 3), (2, 2), (2, 3), (2, 2)]
            assert report["items"][2]["student_evidence"] == "x = 5"
            assert report["items"][2]["scheme_evidence"].startswith("M1")
            assert report_response.text.find(str(tmp_path)) == -1
            assert workspace_children(client) == []

            listed = client.get("/api/corrections").json()["jobs"]
            assert [job["job_id"] for job in listed] == [job_id]
            # Retrieval is from SQLite, not a second provider call.
            assert len(state.requests) == 1

            # A completed job survives a process restart. No provider key is
            # needed just to read the stored result.
            completed_id = job_id

        with client_for(
            monkeypatch, tmp_path, provider_url=url, api_key=None
        ) as restarted:
            assert restarted.get("/api/system/status").json()["correction_engine"][
                "available"
            ] is False
            job = restarted.get(f"/api/corrections/{completed_id}").json()
            assert job["status"] == "completed"
            stored = restarted.get(f"/api/corrections/{completed_id}/report")
            assert stored.status_code == 200
            assert stored.json()["awarded"] == 9
            assert workspace_children(restarted) == []


def test_partial_report_is_persisted_without_a_misleading_percentage(
    monkeypatch, tmp_path
):
    partial = json.loads(json.dumps(MARKING))
    partial["questions"][2] = {
        "label": "3",
        "status": "unreadable",
        "awarded": None,
        "out_of": 3,
        "review_flags": ["answer_extraction_uncertain"],
        "warnings": ["The handwriting is unclear."],
        "feedback": "Could not read the final answer.",
    }
    state = StubState()
    state.responses = [(200, candidate(json.dumps(partial)))]
    with stub_server(state) as url:
        with client_for(monkeypatch, tmp_path, provider_url=url) as client:
            response = submit(client)
            assert response.status_code == 202, response.text
            job_id = response.json()["job_id"]

            completed = wait_for_terminal(client, job_id)
            assert completed["status"] == "completed"
            assert completed["report_status"] == "partial"
            assert completed["percentage"] is None
            assert completed["awarded"] == 7
            assert completed["out_of"] == 10
            assert completed["review_required"] is True

            report = client.get(f"/api/corrections/{job_id}/report").json()
            assert report["status"] == "partial"
            assert report["percentage"] is None
            assert report["unresolved"] == ["3"]
            assert report["items"][2]["status"] == "unreadable"
            assert report["items"][2]["awarded"] is None
            assert report["items"][2]["warnings"] == ["The handwriting is unclear."]
            assert workspace_children(client) == []


def test_provider_failure_marks_the_job_failed_and_keeps_no_report(monkeypatch, tmp_path):
    state = StubState()
    state.responses = [(500, {"error": "upstream unavailable"})]
    with stub_server(state) as url:
        with client_for(monkeypatch, tmp_path, provider_url=url) as client:
            response = submit(client)
            assert response.status_code == 202, response.text
            job_id = response.json()["job_id"]

            failed = wait_for_terminal(client, job_id)
            assert failed["status"] == "failed"
            assert failed["report_status"] is None
            assert failed["awarded"] is None
            assert failed["out_of"] is None
            assert "temporarily unavailable" in failed["error"].lower()
            assert "local-test-key" not in failed["error"]

            report = client.get(f"/api/corrections/{job_id}/report")
            assert report.status_code == 409
            assert report.json()["error"]["code"] == "report_not_ready"
            assert workspace_children(client) == []


def test_invalid_inputs_are_rejected_before_the_provider_is_called(monkeypatch, tmp_path):
    state = StubState()
    with stub_server(state) as url:
        with client_for(monkeypatch, tmp_path, provider_url=url) as client:
            corrupt = submit(client, files=uploads(submission=b"%PDF-1.7 broken"))
            assert corrupt.status_code == 422, corrupt.text
            assert corrupt.json()["error"]["code"] == "unsupported_input"
            assert corrupt.json()["error"]["message"]

            no_scheme = submit(client, files=uploads(include_scheme=False))
            assert no_scheme.status_code == 422

            unsupported = submit(
                client,
                files=[
                    (
                        "files",
                        ("work.txt", b"plain text", "text/plain"),
                    )
                ],
            )
            assert unsupported.status_code == 422

            bad_total = submit(client, data=form(max_score="not-a-number"))
            assert bad_total.status_code == 422

            missing_title = submit(client, data=form(assignment_title=""))
            assert missing_title.status_code == 422

            assert client.get("/api/corrections").json()["jobs"] == []
            assert workspace_children(client) == []
            assert state.requests == []


def test_report_is_not_ready_for_a_queued_job(monkeypatch, tmp_path):
    state = StubState()
    with stub_server(state) as url:
        with client_for(monkeypatch, tmp_path, provider_url=url) as client:
            storage = client.app.state.storage
            storage.create_correction_job(
                job_id="job-queued-test",
                assignment_title="Still waiting",
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

            response = client.get("/api/corrections/job-queued-test/report")
            assert response.status_code == 409
            assert response.json()["error"]["code"] == "report_not_ready"
            assert client.get("/api/corrections/no-such-job").status_code == 404


def test_idempotency_key_prevents_duplicate_jobs(monkeypatch, tmp_path):
    state = StubState()
    state.responses = [(200, candidate(json.dumps(MARKING)))]
    with stub_server(state) as url:
        with client_for(monkeypatch, tmp_path, provider_url=url) as client:
            headers = {"Idempotency-Key": "browser-request-0001"}
            first = submit(client, headers=headers)
            assert first.status_code == 202, first.text
            first_id = first.json()["job_id"]
            wait_for_terminal(client, first_id)

            second = submit(client, headers=headers)
            assert second.status_code == 202, second.text
            assert second.json()["job_id"] == first_id
            assert len(client.get("/api/corrections").json()["jobs"]) == 1
            assert len(state.requests) == 1
            assert workspace_children(client) == []


def test_invalid_idempotency_key_is_rejected(monkeypatch, tmp_path):
    state = StubState()
    with stub_server(state) as url:
        with client_for(monkeypatch, tmp_path, provider_url=url) as client:
            response = submit(client, headers={"Idempotency-Key": "short"})
            assert response.status_code == 422
            assert "Idempotency-Key" in response.json()["error"]["message"]
            assert state.requests == []


def test_missing_engine_configuration_is_an_honest_503(monkeypatch, tmp_path):
    state = StubState()
    with stub_server(state) as url:
        with client_for(
            monkeypatch, tmp_path, provider_url=url, api_key=None
        ) as client:
            response = submit(client)
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "engine_unavailable"
            assert "api key" in response.json()["error"]["message"].lower()
            assert state.requests == []
            assert client.get("/api/corrections").json()["jobs"] == []


def test_upload_limit_from_stored_settings_is_enforced(monkeypatch, tmp_path):
    state = StubState()
    with stub_server(state) as url:
        with client_for(monkeypatch, tmp_path, provider_url=url) as client:
            updated = client.patch("/api/settings", json={"max_upload_mb": 1})
            assert updated.status_code == 200, updated.text
            payload = (FIXTURES / "student_submission.pdf").read_bytes()
            oversized = payload + b"\0" * (1024 * 1024)
            response = submit(client, files=uploads(submission=oversized))
            assert response.status_code == 422
            assert "upload limit" in response.json()["error"]["message"].lower()
            assert state.requests == []
            assert workspace_children(client) == []
