"""Settings API: read and update the small set of operational settings.

Request validation is strict: unknown fields are rejected by Pydantic before
they reach the service, and value/range/choice rules live in one place
(``models.validate_settings_update``).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from ..services import SettingsService
from .deps import get_settings_service

router = APIRouter(prefix="/api", tags=["settings"])


class SettingsUpdate(BaseModel):
    """Partial settings update. Only explicitly supplied keys are changed."""

    model_config = ConfigDict(extra="forbid", strict=True)

    max_upload_mb: int | None = None
    default_feedback_detail: str | None = None


@router.get("/settings")
def read_settings(service: SettingsService = Depends(get_settings_service)) -> dict:
    return {"settings": service.get()}


@router.patch("/settings")
def update_settings(
    payload: SettingsUpdate,
    service: SettingsService = Depends(get_settings_service),
) -> dict:
    changes = payload.model_dump(exclude_unset=True)
    return {"settings": service.update(changes)}
