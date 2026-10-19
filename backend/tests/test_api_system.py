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
    assert data["version"] == "6.0.0"
    assert data["phase"] == 1

    features = data["features"]
    # Phase 1 reality: UI-level features work, processing features do not.
    assert features["file_selection"] is True
    assert features["ui_preferences"] is True
    assert features["storage_overview"] is True
    assert features["ai_correction"] is False
    assert features["pdf_processing"] is False
    assert features["grade_submission"] is False
    assert features["reports"] is False
    assert features["classroom_sync"] is False
    assert features["background_tasks"] is False


def test_status_reflects_real_configuration(client, monkeypatch):
    assert client.get("/api/system/status").json()["ai_provider_configured"] is False
    assert client.get("/api/system/status").json()["classroom_configured"] is False

    monkeypatch.setenv("MC6_AI_API_KEY", "fake-key-for-test")
    monkeypatch.setenv("MC6_GOOGLE_OAUTH_CLIENT", "/some/path.json")
    data = client.get("/api/system/status").json()
    assert data["ai_provider_configured"] is True
    assert data["classroom_configured"] is True


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


def test_unknown_api_route_is_404(client):
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
