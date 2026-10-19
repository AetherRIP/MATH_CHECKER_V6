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
APP_VERSION = "6.1.0"
APP_PHASE = 2

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
        # SQLite lives inside the configured data directory so MC6_DATA_DIR
        # remains the single storage override for local and cloud runs.
        database_path=data_dir / "app.db",
    )


def ensure_dirs() -> Config:
    """Create the runtime data directories if missing. Idempotent."""
    cfg = get_config()
    for directory in (cfg.data_dir, cfg.tmp_dir, cfg.data_dir / "reports", cfg.data_dir / "cache"):
        directory.mkdir(parents=True, exist_ok=True)
    return cfg


def ai_provider_configured() -> bool:
    """True when an AI provider key is present (Phase 2+ feature)."""
    return bool(os.environ.get("MC6_AI_API_KEY", "").strip())


def classroom_configured() -> bool:
    """True when Google Classroom OAuth material is configured (later phase)."""
    return bool(os.environ.get("MC6_GOOGLE_OAUTH_CLIENT", "").strip())
