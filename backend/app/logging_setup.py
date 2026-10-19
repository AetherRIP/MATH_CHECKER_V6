"""Lightweight application logging.

The application logger is separate from uvicorn's access logger. Request
handling will attach a generated request id to this context; log records
without one still work (``-`` is shown). No log message should contain API
keys, credentials or student submission content.
"""

from __future__ import annotations

import logging
import sys
import uuid
from contextvars import ContextVar
from typing import TextIO

APP_LOGGER_NAME = "mathchecker"

_request_id: ContextVar[str | None] = ContextVar("mc6_request_id", default=None)


class RequestIdFilter(logging.Filter):
    """Ensure every record has a request_id attribute for the formatter."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "request_id", None):
            record.request_id = current_request_id() or "-"
        return True


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


def set_request_id(value: str | None) -> None:
    _request_id.set(value)


def current_request_id() -> str | None:
    return _request_id.get()


def configure_logging(level: str = "INFO", *, stream: TextIO | None = None) -> logging.Logger:
    """Configure the application logger once, without touching root logging."""
    logger = logging.getLogger(APP_LOGGER_NAME)
    logger.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s [%(request_id)s]: %(message)s"
        )
    )
    handler.addFilter(RequestIdFilter())
    logger.addHandler(handler)
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    return logging.getLogger(APP_LOGGER_NAME if not name else f"{APP_LOGGER_NAME}.{name}")
