"""Database statistics API.

Counts come from the local SQLite database only. Responses contain numbers,
status strings and the schema version — never filesystem paths, record
contents or student data.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..services import StatsService
from .deps import get_stats_service

router = APIRouter(prefix="/api", tags=["database"])


@router.get("/database/stats")
def database_stats(service: StatsService = Depends(get_stats_service)) -> dict:
    return service.snapshot()
