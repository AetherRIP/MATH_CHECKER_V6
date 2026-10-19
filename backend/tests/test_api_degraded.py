"""Degraded-start behaviour: a broken database must not take the app down."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

import app.main as app_main
from app.db import DatabaseError


def _client_with_failing_database(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setenv("MC6_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MC6_LOG_LEVEL", "WARNING")
    monkeypatch.delenv("MC6_TMP_DIR", raising=False)
    monkeypatch.setattr("app.config.ENV_FILE", tmp_path / "no-such.env")

    def fail_initialize(self):
        raise DatabaseError("simulated initialization failure")

    monkeypatch.setattr(app_main.Database, "initialize", fail_initialize)
    return TestClient(app_main.app)


def test_degraded_start_serves_health_and_reports_unavailable(monkeypatch, tmp_path):
    with _client_with_failing_database(monkeypatch, tmp_path) as client:
        # Liveness and the static UI still work.
        assert client.get("/api/health").json() == {"status": "ok"}
        assert client.get("/").status_code == 200

        status = client.get("/api/system/status").json()
        assert status["database"]["status"] == "unavailable"
        assert status["database"]["schema_version"] is None
        assert "simulated" not in json.dumps(status)

        for path in ("/api/settings", "/api/database/stats"):
            response = client.get(path)
            assert response.status_code == 503, path
            body = response.json()
            assert body["error"]["code"] == "database_unavailable", path
            assert body["error"]["message"], path
            assert body["error"]["request_id"], path
            assert "simulated" not in response.text, path
            assert "app.db" not in response.text, path
            assert str(tmp_path) not in response.text, path


def test_degraded_start_still_rejects_invalid_settings(monkeypatch, tmp_path):
    with _client_with_failing_database(monkeypatch, tmp_path) as client:
        # The dependency check runs before validation, so a degraded app
        # answers 503 with the same safe envelope rather than a stack trace.
        response = client.patch("/api/settings", json={"max_upload_mb": 0})
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "database_unavailable"
