"""Dependency providers for API routes.

Routes never construct a database connection. They ask for the storage
boundary or a service; when the application started degraded, the request
fails with a safe 503 envelope instead of a stack trace.
"""

from __future__ import annotations

from fastapi import Request

from ..db import DATABASE_UNAVAILABLE_DETAIL
from ..services import SettingsService, StatsService
from ..storage import Storage
from .errors import ApiError


def get_storage(request: Request) -> Storage:
    storage = getattr(request.app.state, "storage", None)
    if storage is None:
        raise ApiError(503, "database_unavailable", DATABASE_UNAVAILABLE_DETAIL)
    return storage


def get_settings_service(request: Request) -> SettingsService:
    return SettingsService(get_storage(request))


def get_stats_service(request: Request) -> StatsService:
    return StatsService(get_storage(request))
