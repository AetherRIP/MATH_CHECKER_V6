#!/usr/bin/env python3
"""Math Checker V6 — startup entry point.

Usage:
    python main.py                  # http://127.0.0.1:8643 (configurable)
    python main.py --port 9000      # override the port
    python main.py --host 0.0.0.0   # listen on all interfaces (explicit opt-in)

Configuration comes from MC6_* environment variables and an optional .env
file (see .env.example). No AI key or credential is required to start.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent / "backend"
sys.path.insert(0, str(BACKEND))


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python main.py",
        description="Math Checker V6 — AI-assisted mathematics homework correction (Phase 1 foundation).",
    )
    parser.add_argument("--host", help="interface to bind (default: MC6_HOST or 127.0.0.1)")
    parser.add_argument("--port", type=int, help="port to listen on (default: MC6_PORT or 8643)")
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    from app.config import (
        APP_NAME,
        APP_VERSION,
        ConfigError,
        ai_provider_configured,
        classroom_configured,
        ensure_dirs,
        get_config,
    )

    if args.version:
        print(f"{APP_NAME} {APP_VERSION}")
        return 0

    try:
        cfg = get_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    host = args.host or cfg.host
    port = args.port if args.port is not None else cfg.port
    if not 1 <= port <= 65535:
        print("Configuration error: port must be between 1 and 65535.", file=sys.stderr)
        return 2

    ensure_dirs()

    print(f"{APP_NAME} v{APP_VERSION} (Phase 1)")
    if not ai_provider_configured():
        print("Note: no AI provider is configured — the UI runs fully without one.")
    if not classroom_configured():
        print("Note: Google Classroom integration arrives in a later phase.")
    print(f"Serving on http://{host}:{port}  (Ctrl+C to stop)")

    import uvicorn

    from app.main import app

    uvicorn.run(app, host=host, port=port, log_level=cfg.log_level.lower())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
