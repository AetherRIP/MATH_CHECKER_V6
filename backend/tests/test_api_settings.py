"""Tests for the settings API."""

from __future__ import annotations

import io

from app.logging_setup import configure_logging


def test_get_settings_returns_defaults(client):
    response = client.get("/api/settings")
    assert response.status_code == 200
    assert response.json() == {
        "settings": {
            "max_upload_mb": 25,
            "default_feedback_detail": "detailed",
        }
    }


def test_patch_settings_updates_and_persists(client):
    response = client.patch(
        "/api/settings",
        json={"max_upload_mb": 10, "default_feedback_detail": "brief"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "settings": {
            "max_upload_mb": 10,
            "default_feedback_detail": "brief",
        }
    }
    assert client.get("/api/settings").json()["settings"] == {
        "max_upload_mb": 10,
        "default_feedback_detail": "brief",
    }


def test_patch_settings_rejects_invalid_payloads_with_an_envelope(client, tmp_path):
    invalid_payloads = (
        {},
        {"unknown_setting": 1},
        {"max_upload_mb": 0},
        {"max_upload_mb": 26},
        {"max_upload_mb": "10"},
        {"max_upload_mb": True},
        {"max_upload_mb": None},
        {"default_feedback_detail": "verbose"},
        {"default_feedback_detail": None},
    )

    for payload in invalid_payloads:
        response = client.patch("/api/settings", json=payload)
        assert response.status_code == 422, payload
        body = response.json()
        assert body["error"]["code"] == "invalid_request", payload
        assert body["error"]["message"], payload
        assert body["error"]["request_id"], payload
        assert str(tmp_path) not in response.text, payload
        assert "MC6_" not in response.text, payload

    # A rejected update must not change the stored settings.
    assert client.get("/api/settings").json()["settings"] == {
        "max_upload_mb": 25,
        "default_feedback_detail": "detailed",
    }


def test_unknown_settings_field_is_reported_without_its_value(client):
    response = client.patch(
        "/api/settings", json={"api_key": "super-secret-value-123"}
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "invalid_request"
    assert "super-secret-value-123" not in response.text
    assert body["error"]["fields"][0]["field"] == "api_key"


def test_settings_values_are_never_written_to_logs(client):
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)

    response = client.patch(
        "/api/settings", json={"default_feedback_detail": "brief"}
    )
    assert response.status_code == 200

    logged = stream.getvalue()
    assert "default_feedback_detail" in logged
    assert "brief" not in logged


def test_invalid_settings_values_are_never_written_to_logs(client):
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)

    response = client.patch("/api/settings", json={"max_upload_mb": 999})

    assert response.status_code == 422
    assert "999" not in stream.getvalue()
