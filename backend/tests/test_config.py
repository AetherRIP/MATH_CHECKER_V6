"""Tests for configuration loading (MC6_* variables and the .env loader)."""

from __future__ import annotations

import os

import pytest


def test_defaults(client, monkeypatch):
    from app.config import get_config

    monkeypatch.delenv("MC6_LOG_LEVEL", raising=False)
    cfg = get_config()
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 8643
    assert cfg.debug is False
    assert cfg.log_level == "INFO"
    assert cfg.database_path == cfg.data_dir / "app.db"


def test_environment_overrides(client, monkeypatch):
    from app.config import get_config

    monkeypatch.setenv("MC6_HOST", "0.0.0.0")
    monkeypatch.setenv("MC6_PORT", "9001")
    monkeypatch.setenv("MC6_DEBUG", "true")
    monkeypatch.setenv("MC6_LOG_LEVEL", "debug")

    cfg = get_config()
    assert cfg.host == "0.0.0.0"
    assert cfg.port == 9001
    assert cfg.debug is True
    assert cfg.log_level == "DEBUG"


def test_invalid_port_rejected(client, monkeypatch):
    from app.config import ConfigError, get_config

    monkeypatch.setenv("MC6_PORT", "not-a-number")
    with pytest.raises(ConfigError):
        get_config()

    monkeypatch.setenv("MC6_PORT", "70000")
    with pytest.raises(ConfigError):
        get_config()


def test_invalid_log_level_rejected(client, monkeypatch):
    from app.config import ConfigError, get_config

    monkeypatch.setenv("MC6_LOG_LEVEL", "chatty")
    with pytest.raises(ConfigError):
        get_config()


def test_env_file_fills_missing_values_and_env_wins(client, monkeypatch, tmp_path):
    from app.config import load_env_file

    env_file = tmp_path / "sample.env"
    env_file.write_text(
        "# comment line\n"
        "MC6_PORT=9500\n"
        "MC6_HOST=10.0.0.5\n"
        "MC6_LOG_LEVEL=ERROR\n"
        "BAD KEY=1\n"
        "QUOTED=\"quoted value\"\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("MC6_HOST", "192.168.1.9")  # present: must win
    monkeypatch.delenv("MC6_PORT", raising=False)
    monkeypatch.delenv("MC6_LOG_LEVEL", raising=False)
    monkeypatch.delenv("QUOTED", raising=False)

    load_env_file(env_file)

    assert os.environ["MC6_HOST"] == "192.168.1.9"
    assert os.environ["MC6_PORT"] == "9500"
    assert os.environ["MC6_LOG_LEVEL"] == "ERROR"
    assert os.environ["QUOTED"] == "quoted value"
    assert "BAD KEY" not in os.environ


def test_env_file_missing_is_silent(client, tmp_path):
    from app.config import load_env_file

    load_env_file(tmp_path / "does-not-exist.env")  # must not raise


def test_ai_and_classroom_flags_read_real_environment(client, monkeypatch):
    from app.config import ai_provider_configured, classroom_configured

    monkeypatch.delenv("MC6_AI_API_KEY", raising=False)
    monkeypatch.delenv("MC6_GOOGLE_OAUTH_CLIENT", raising=False)
    assert ai_provider_configured() is False
    assert classroom_configured() is False

    monkeypatch.setenv("MC6_AI_API_KEY", "x")
    monkeypatch.setenv("MC6_GOOGLE_OAUTH_CLIENT", "y")
    assert ai_provider_configured() is True
    assert classroom_configured() is True
