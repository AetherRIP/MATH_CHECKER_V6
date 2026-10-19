"""Shared fixtures for the Math Checker V6 backend tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolated TestClient: scratch data dir, no .env, no integrations set."""
    monkeypatch.setenv("MC6_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MC6_LOG_LEVEL", "WARNING")
    monkeypatch.delenv("MC6_TMP_DIR", raising=False)
    monkeypatch.delenv("MC6_AI_API_KEY", raising=False)
    monkeypatch.delenv("MC6_GOOGLE_OAUTH_CLIENT", raising=False)
    monkeypatch.delenv("MC6_HOST", raising=False)
    monkeypatch.delenv("MC6_PORT", raising=False)
    monkeypatch.delenv("MC6_DEBUG", raising=False)

    # A developer's local .env must never leak into test expectations: point
    # the loader at a file that does not exist. Explicit load_env_file(path)
    # calls in tests still exercise the real loader.
    monkeypatch.setattr("app.config.ENV_FILE", tmp_path / "no-such.env")

    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
