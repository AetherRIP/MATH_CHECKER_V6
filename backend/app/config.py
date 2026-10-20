"""Central configuration for Math Checker V6.

All server-side configuration comes from ``MC6_*`` environment variables.
An optional ``.env`` file in the project root may provide defaults; values
already present in the process environment always win over the file.

No secret value is ever logged, and no configuration value other than the
small, explicitly listed set in ``app.api.system`` is ever returned by an API
response. Server filesystem paths never leave the process.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "Math Checker V6"
APP_VERSION = "6.4.0"
APP_PHASE = 8

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8643
_VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PORT_ERROR = "port must be an integer between 1 and 65535 (set via MC6_PORT or --port)"


class ConfigError(ValueError):
    """Raised when a configuration value is present but invalid."""


def load_env_file(path: Path | None = None) -> None:
    """Minimal ``.env`` loader (stdlib only).

    Only variables missing from the process environment are set, so real
    environment variables always win. Values are never logged.
    """
    path = path or ENV_FILE
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if _ENV_KEY_RE.match(key):
            os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Config:
    host: str
    port: int
    debug: bool
    log_level: str
    data_dir: Path
    tmp_dir: Path
    uploads_dir: Path
    database_path: Path


def get_config(host: str | None = None, port: int | None = None) -> Config:
    """Read the current configuration from the environment.

    Optional ``host``/``port`` overrides (the CLI flags) are resolved and
    validated here too, so every configuration rule — defaults, env parsing
    and overrides — has exactly one owner.
    """
    load_env_file()

    host = (host or "").strip() or os.environ.get("MC6_HOST", "").strip() or _DEFAULT_HOST

    if port is None:
        port_raw = os.environ.get("MC6_PORT", "").strip() or str(_DEFAULT_PORT)
        try:
            port = int(port_raw)
        except ValueError as exc:
            raise ConfigError(_PORT_ERROR) from exc
    if not 1 <= port <= 65535:
        raise ConfigError(_PORT_ERROR)

    debug = os.environ.get("MC6_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}

    level = os.environ.get("MC6_LOG_LEVEL", "").strip().upper() or "INFO"
    if level not in _VALID_LOG_LEVELS:
        raise ConfigError(
            "MC6_LOG_LEVEL must be one of: " + ", ".join(_VALID_LOG_LEVELS)
        )

    data_raw = os.environ.get("MC6_DATA_DIR", "").strip()
    data_dir = (
        Path(data_raw).expanduser() if data_raw else PROJECT_ROOT / "data"
    )
    tmp_raw = os.environ.get("MC6_TMP_DIR", "").strip()
    tmp_dir = Path(tmp_raw).expanduser() if tmp_raw else data_dir / "tmp"

    return Config(
        host=host,
        port=port,
        debug=debug,
        log_level=level,
        data_dir=data_dir,
        tmp_dir=tmp_dir,
        uploads_dir=data_dir / "uploads",
        # SQLite lives inside the configured data directory so MC6_DATA_DIR
        # remains the single storage override for local and cloud runs.
        database_path=data_dir / "app.db",
    )


def ensure_dirs() -> Config:
    """Create the runtime data directories if missing. Idempotent."""
    cfg = get_config()
    for directory in (
        cfg.data_dir,
        cfg.tmp_dir,
        cfg.uploads_dir,
        cfg.data_dir / "reports",
        cfg.data_dir / "cache",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    return cfg


def ai_provider_configured() -> bool:
    """True when an AI provider key is present (Phase 3 feature)."""
    return bool(os.environ.get("MC6_AI_API_KEY", "").strip())


@dataclass(frozen=True)
class AIConfig:
    """Server-side AI provider configuration. The key never leaves the process."""

    api_key: str
    model: str
    base_url: str
    timeout_seconds: int
    max_retries: int


def get_ai_config() -> AIConfig | None:
    """Return the provider configuration, or ``None`` when no key is set.

    Invalid optional values raise :class:`ConfigError` with a message that
    names the variable but never its value (a key must never reach a log or
    an error response).
    """
    api_key = os.environ.get("MC6_AI_API_KEY", "").strip()
    if not api_key:
        return None

    model = os.environ.get("MC6_AI_MODEL", "").strip() or "gemini-3.5-flash-lite"
    base_url = (
        os.environ.get("MC6_AI_BASE_URL", "").strip()
        or "https://generativelanguage.googleapis.com"
    ).rstrip("/")
    if not base_url.startswith(("https://", "http://")):
        raise ConfigError("MC6_AI_BASE_URL must be an http(s) URL.")

    timeout_raw = os.environ.get("MC6_AI_TIMEOUT_SECONDS", "").strip() or "180"
    try:
        timeout_seconds = int(timeout_raw)
    except ValueError as exc:
        raise ConfigError("MC6_AI_TIMEOUT_SECONDS must be an integer.") from exc
    if not 5 <= timeout_seconds <= 600:
        raise ConfigError("MC6_AI_TIMEOUT_SECONDS must be between 5 and 600.")

    retries_raw = os.environ.get("MC6_AI_MAX_RETRIES", "").strip() or "2"
    try:
        max_retries = int(retries_raw)
    except ValueError as exc:
        raise ConfigError("MC6_AI_MAX_RETRIES must be an integer.") from exc
    if not 0 <= max_retries <= 5:
        raise ConfigError("MC6_AI_MAX_RETRIES must be between 0 and 5.")

    return AIConfig(
        api_key=api_key,
        model=model,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )


def classroom_oauth_client_path() -> Path | None:
    """Resolve the Google OAuth client JSON path, or None when absent.

    Sources, in order:
    1. ``MC6_GOOGLE_OAUTH_CLIENT`` — an explicit path (or inline ``{...}``
       JSON, which is written to the secrets directory; the value is never
       logged or echoed).
    2. ``<data_dir>/secrets/google_oauth_client.json`` — the V5 convention,
       so an existing V5 credentials file can be dropped into V6's data
       directory without any code change.

    The file itself must contain an ``installed`` or ``web`` client object
    (the Google "client secret" JSON). The refresh token lives in the local
    store, never inside this file.
    """
    explicit = os.environ.get("MC6_GOOGLE_OAUTH_CLIENT", "").strip()
    if explicit:
        if explicit.startswith("{"):
            destination = get_config().data_dir / "secrets" / "google_oauth_client.json"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(explicit, encoding="utf-8")
            return destination
        return Path(explicit).expanduser()
    return get_config().data_dir / "secrets" / "google_oauth_client.json"


def classroom_client_configured() -> bool:
    """True when a usable Google OAuth client JSON exists on disk."""
    path = classroom_oauth_client_path()
    try:
        if path is None or not path.is_file() or path.stat().st_size == 0:
            return False
        import json

        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(payload, dict):
        return False
    return bool(payload.get("installed") or payload.get("web"))


def classroom_refresh_token_path() -> Path:
    """Local file holding the OAuth refresh token (never committed, never logged)."""
    return get_config().data_dir / "secrets" / "classroom_refresh_token"


def classroom_configured() -> bool:
    """True when the OAuth client JSON AND a stored refresh token both exist."""
    if not classroom_client_configured():
        return False
    refresh_path = classroom_refresh_token_path()
    try:
        return bool(refresh_path.read_text(encoding="utf-8").strip())
    except OSError:
        return False
