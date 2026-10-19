"""Application error handlers.

All handlers return the shared error envelope, log diagnostics server-side,
and never echo request bodies, credentials, filesystem paths or submitted
student content.
"""

from __future__ import annotations

import logging
import sqlite3

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ..logging_setup import new_request_id
from ..models import SettingsValidationError
from .errors import ApiError, error_envelope

log = logging.getLogger("mathchecker.api")

_DATABASE_UNAVAILABLE = "The local database is not available."
_INVALID_REQUEST = "The request could not be processed because it contains invalid data."
_INTERNAL_ERROR = "An unexpected error occurred."


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or new_request_id()


def _json(
    status_code: int,
    *,
    code: str,
    message: str,
    request_id: str,
    fields: list[dict[str, str]] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=error_envelope(
            code=code, message=message, request_id=request_id, fields=fields
        ),
        headers={"X-Request-ID": request_id},
    )


def _validation_fields(exc: RequestValidationError) -> list[dict[str, str]]:
    """Value-free field errors: only the location and the human message."""
    fields: list[dict[str, str]] = []
    for error in exc.errors():
        location = [str(part) for part in error.get("loc", ()) if part not in ("body", "query")]
        fields.append(
            {
                "field": ".".join(location) or "body",
                "message": str(error.get("msg", "Invalid value.")),
            }
        )
    return fields


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        request_id = _request_id(request)
        log.log(
            logging.WARNING if exc.status_code >= 500 else logging.INFO,
            "api error [%s] %s %s -> %s %s",
            request_id,
            request.method,
            request.url.path,
            exc.status_code,
            exc.code,
        )
        return _json(
            exc.status_code,
            code=exc.code,
            message=exc.message,
            request_id=request_id,
            fields=exc.fields,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        request_id = _request_id(request)
        log.info(
            "invalid request [%s] %s %s",
            request_id,
            request.method,
            request.url.path,
        )
        return _json(
            422,
            code="invalid_request",
            message=_INVALID_REQUEST,
            request_id=request_id,
            fields=_validation_fields(exc),
        )

    @app.exception_handler(SettingsValidationError)
    async def handle_settings_error(
        request: Request, exc: SettingsValidationError
    ) -> JSONResponse:
        request_id = _request_id(request)
        log.info(
            "invalid settings [%s] %s %s",
            request_id,
            request.method,
            request.url.path,
        )
        return _json(
            422,
            code="invalid_request",
            message=str(exc),
            request_id=request_id,
        )

    @app.exception_handler(sqlite3.Error)
    async def handle_database_error(request: Request, exc: sqlite3.Error) -> JSONResponse:
        request_id = _request_id(request)
        log.exception(
            "database error [%s] %s %s",
            request_id,
            request.method,
            request.url.path,
        )
        return _json(
            503,
            code="database_unavailable",
            message=_DATABASE_UNAVAILABLE,
            request_id=request_id,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        request_id = _request_id(request)
        log.exception(
            "unhandled error [%s] %s %s",
            request_id,
            request.method,
            request.url.path,
        )
        return _json(
            500,
            code="internal_error",
            message=_INTERNAL_ERROR,
            request_id=request_id,
        )
