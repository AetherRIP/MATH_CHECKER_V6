"""End-to-end walkthrough: real server, real engine, stub provider, no network.

Runs the EXACT code paths a user runs:

    .venv/Scripts/python scripts/e2e_walkthrough.py            # one-shot
    .venv/Scripts/python scripts/e2e_walkthrough.py --keep-alive
                                                              # stay up and
                                                              # print the
                                                              # results deep link

The stub Gemini provider is a local HTTP server, so the full path
(multipart upload -> workspace -> extraction -> prompt -> HTTP transport ->
JSON validation -> deterministic checks -> SQLite) runs without contacting a
paid external service, matching the offline test suite's approach.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "backend" / "tests" / "fixtures" / "v5"
PY = sys.executable

# Same deterministic marking decisions as the automated suite's stub.
MARKING = {
    "summary": "Four questions marked.",
    "questions": [
        {"label": "1", "status": "marked", "awarded": 3, "out_of": 3,
         "student_answer": "4", "scheme_answer": "4",
         "student_evidence": "2 + 2 = 4", "scheme_evidence": "B3 for 4",
         "feedback": "Correct."},
        {"label": "2", "status": "marked", "awarded": 2, "out_of": 2,
         "student_answer": "7", "scheme_answer": "7", "feedback": "Correct."},
        {"label": "3", "status": "marked", "awarded": 2, "out_of": 3,
         "student_answer": "5", "scheme_answer": "6",
         "student_evidence": "x = 5", "scheme_evidence": "M1 A1 A1 for x = 6",
         "feedback": "Method accepted; final value is wrong."},
        {"label": "4", "status": "marked", "awarded": 2, "out_of": 2,
         "student_answer": "12", "scheme_answer": "12", "feedback": "Correct."},
    ],
    "warnings": [],
}


def free_port() -> int:
    with closing(socket.socket()) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def start_stub() -> tuple[ThreadingHTTPServer, str]:
    payload = json.dumps({
        "candidates": [
            {"content": {"parts": [{"text": json.dumps(MARKING)}]},
             "finishReason": "STOP"}
        ]
    }).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - stdlib naming
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_port}"


def start_app(data_dir: Path, provider_url: str, port: int) -> subprocess.Popen:
    env = dict(os.environ)
    env.update({
        "MC6_DATA_DIR": str(data_dir),
        "MC6_HOST": "127.0.0.1",
        "MC6_PORT": str(port),
        "MC6_LOG_LEVEL": "INFO",
        "MC6_AI_API_KEY": "local-walkthrough-key",
        "MC6_AI_BASE_URL": provider_url,
        "MC6_AI_MODEL": "gemini-walkthrough",
        "MC6_AI_MAX_RETRIES": "0",
        "MC6_AI_TIMEOUT_SECONDS": "20",
    })
    process = subprocess.Popen(
        [PY, str(ROOT / "main.py")], env=env, cwd=str(ROOT),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return process


def wait_healthy(port: int, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/api/health"
    import urllib.request
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return
        except Exception:
            time.sleep(0.3)
    raise SystemExit("the application did not become healthy in time")


def api(port: int, path: str, *, method: str = "GET", body: bytes | None = None,
        headers: dict | None = None, timeout: float = 30.0):
    import urllib.request

    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=body, method=method)
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep-alive", action="store_true",
                        help="leave the app running after asserting")
    args = parser.parse_args()

    data_dir = Path(tempfile.mkdtemp(prefix="mc6-e2e-"))
    stub, stub_url = start_stub()
    port = free_port()
    process = start_app(data_dir, stub_url, port)
    print(f"[e2e] data dir : {data_dir}")
    print(f"[e2e] app      : http://127.0.0.1:{port}/  (stub provider {stub_url})")
    try:
        wait_healthy(port)
        status = api(port, "/api/system/status")[1]
        assert status["correction_engine"]["available"] is True, status

        boundary = uuid.uuid4().hex
        files = [
            ("files", ("student_submission.pdf",
                       (FIXTURES / "student_submission.pdf").read_bytes(),
                       "application/pdf")),
            ("mark_scheme_files", ("mark_scheme.pdf",
                                   (FIXTURES / "mark_scheme.pdf").read_bytes(),
                                   "application/pdf")),
        ]
        parts: list[bytes] = []
        for field, (filename, content, ctype) in files:
            parts.append(
                f"--{boundary}\r\nContent-Disposition: form-data; "
                f'name="{field}"; filename="{filename}"\r\n'
                f"Content-Type: {ctype}\r\n\r\n".encode() + content + b"\r\n")
        for field, value in (("assignment_title", "E2E walkthrough"),
                             ("instructions", "Show all working."),
                             ("feedback_detail", "detailed")):
            parts.append(
                f"--{boundary}\r\nContent-Disposition: form-data; "
                f'name="{field}"\r\n\r\n{value}\r\n'.encode())
        parts.append(f"--{boundary}--\r\n".encode())
        headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Idempotency-Key": f"e2e-walkthrough-{uuid.uuid4()}",
        }
        code, created = api(port, "/api/corrections", method="POST",
                            body=b"".join(parts), headers=headers)
        assert code == 202, (code, created)
        job_id = created["job_id"]
        print(f"[e2e] submitted  : job {job_id}")

        deadline = time.time() + 30
        while True:
            code, job = api(port, f"/api/corrections/{job_id}")
            assert code == 200
            if job["status"] in ("completed", "failed"):
                break
            assert time.time() < deadline, job
            time.sleep(0.25)
        assert job["status"] == "completed", job
        print(f"[e2e] completed  : {job['awarded']}/{job['out_of']}"
              f" ({job['percentage']}%)")

        code, report = api(port, f"/api/corrections/{job_id}/report")
        assert code == 200 and report["status"] == "completed"
        assert (report["awarded"], report["out_of"]) == (9, 10), report
        assert [i["awarded"] for i in report["items"]] == [3, 2, 2, 2]

        deep_link = f"http://127.0.0.1:{port}/#/correction?job={job_id}"
        print("[e2e] PASS: upload -> engine -> persisted report -> API verified")
        print(f"[e2e] results deep link: {deep_link}")
        if args.keep_alive:
            print("[e2e] keeping the app RUNNING; Ctrl+C to stop")
            try:
                while True:
                    time.sleep(3600)
            except KeyboardInterrupt:
                pass
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        stub.shutdown()


if __name__ == "__main__":
    sys.exit(main())
