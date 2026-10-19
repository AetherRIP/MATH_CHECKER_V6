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
        description="Math Checker V6 — AI-assisted mathematics homework correction (Phase 3 correction engine).",
    )
    parser.add_argument("--host", help="interface to bind (default: MC6_HOST or 127.0.0.1)")
    parser.add_argument("--port", type=int, help="port to listen on (default: MC6_PORT or 8643)")
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    parser.add_argument(
        "--seed-dev",
        action="store_true",
        help="insert deterministic development fixtures and exit",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    from app.config import (
        APP_NAME,
        APP_PHASE,
        APP_VERSION,
        ConfigError,
        ai_provider_configured,
        classroom_configured,
        get_config,
    )

    if args.version:
        print(f"{APP_NAME} {APP_VERSION}")
        return 0

    try:
        cfg = get_config(host=args.host, port=args.port)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    if args.seed_dev:
        from app.config import ensure_dirs
        from app.db import Database
        from app.dev_fixtures import seed_development_data
        from app.storage import Storage

        try:
            data_cfg = ensure_dirs()
            database = Database(data_cfg.database_path)
            database.initialize()
            result = seed_development_data(Storage(database))
        except Exception as exc:  # report the failure instead of a traceback
            print(f"Could not seed development fixtures: {exc}", file=sys.stderr)
            return 1
        summary = ", ".join(f"{key}={value}" for key, value in result.items())
        print(f"Development fixtures ready in {data_cfg.database_path.name}: {summary}")
        return 0

    print(f"{APP_NAME} v{APP_VERSION} (Phase {APP_PHASE})")
    if not ai_provider_configured():
        print(
            "Note: no AI provider is configured — correction is unavailable "
            "until MC6_AI_API_KEY is set."
        )
    if not classroom_configured():
        print("Note: Google Classroom integration arrives in a later phase.")
    print(f"Serving on http://{cfg.host}:{cfg.port}  (Ctrl+C to stop)")

    import uvicorn

    from app.main import app

    uvicorn.run(
        app,
        host=cfg.host,
        port=cfg.port,
        log_level=cfg.log_level.lower(),
        # Request logging is owned by the application middleware, so routine
        # health checks cannot flood the access log.
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
