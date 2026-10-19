"""Tests for /api/health and /api/system/status."""

from __future__ import annotations

import json


def test_health_returns_ok(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_status_shape_and_honest_feature_flags(client):
    response = client.get("/api/system/status")
    assert response.status_code == 200
    data = response.json()

    assert data["app_name"] == "Math Checker V6"
    assert data["version"] == "6.2.0"
    assert data["phase"] == 3

    assert data["database"] == {
        "status": "ready",
        "schema_version": 1,
        "detail": None,
    }

    features = data["features"]
    # Implemented now.
    assert features["file_selection"] is True
    assert features["ui_preferences"] is True
    assert features["storage_overview"] is True
    assert features["database"] is True
    assert features["settings"] is True
    # PDF extraction is implemented; correction needs a configured provider.
    assert features["pdf_processing"] is True
    assert features["ai_correction"] is False
    assert features["grade_submission"] is False
    # Report files and the Phase 4 job lifecycle are not implemented.
    assert features["reports"] is False
    assert features["classroom_sync"] is False
    assert features["background_tasks"] is False

    engine = data["correction_engine"]
    assert engine == {
        "name": "unavailable",
        "available": False,
        "reason": "No AI provider is configured. Set MC6_AI_API_KEY to enable correction.",
    }


def test_status_reflects_real_configuration(client, monkeypatch):
    assert client.get("/api/system/status").json()["ai_provider_configured"] is False
    assert client.get("/api/system/status").json()["classroom_configured"] is False

    monkeypatch.setenv("MC6_AI_API_KEY", "fake-key-for-test")
    monkeypatch.setenv("MC6_GOOGLE_OAUTH_CLIENT", "/some/path.json")
    data = client.get("/api/system/status").json()
    assert data["ai_provider_configured"] is True
    assert data["classroom_configured"] is True
    assert data["features"]["ai_correction"] is True
    assert data["features"]["grade_submission"] is True
    assert data["correction_engine"]["available"] is True
    assert data["correction_engine"]["name"] == "gemini:gemini-2.5-flash"
    assert data["correction_engine"]["reason"] is None
    assert "fake-key-for-test" not in client.get("/api/system/status").text


def test_status_never_leaks_secrets_paths_or_env_names(client, monkeypatch, tmp_path):
    monkeypatch.setenv("MC6_AI_API_KEY", "super-secret-value-123")
    body = client.get("/api/system/status").text

    assert "super-secret-value-123" not in body
    assert "MC6_" not in body
    assert str(tmp_path) not in body
    assert str(tmp_path).replace("\\", "/") not in body
    assert ".env" not in body


def test_status_payload_is_plain_json_scalars(client):
    data = client.get("/api/system/status").json()
    # Sanity: the payload serialises cleanly and contains no nested surprises.
    assert json.loads(json.dumps(data)) == data


def test_request_id_header_is_present(client):
    assert client.get("/api/health").headers.get("x-request-id")
    assert client.get("/api/system/status").headers.get("x-request-id")


def test_openapi_document_is_available(client):
    response = client.get("/api/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Math Checker V6"


def test_unknown_api_route_uses_the_error_envelope(client):
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert body["error"]["message"]
    assert body["error"]["request_id"]
    assert "detail" not in body


def test_disallowed_api_method_uses_the_error_envelope(client):
    response = client.post("/api/health")
    assert response.status_code == 405
    body = response.json()
    assert body["error"]["code"] == "method_not_allowed"
    assert body["error"]["message"]
    assert body["error"]["request_id"]
    assert "detail" not in body
    assert "GET" in response.headers.get("allow", "")
