"""API error type and the shared error envelope.

Every API failure returns the same shape::

    {"error": {"code": "...", "message": "...", "request_id": "..."}}

Validation failures add ``fields`` with per-field, value-free details.
Messages are user-safe; diagnostics belong in the server log.
"""

from __future__ import annotations

from typing import Any


class ApiError(Exception):
    """A deliberate API failure with a safe message and a status code."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        fields: list[dict[str, str]] | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.fields = fields


def error_envelope(
    *,
    code: str,
    message: str,
    request_id: str,
    fields: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": request_id,
    }
    if fields:
        error["fields"] = fields
    return {"error": error}
