"""Application services for Phase 2.

Services own policy that is not a database concern:

* settings validation and the audit log of which keys changed;
* a readiness-checked database statistics snapshot.

They return plain Python values so API routes and tests do not depend on the
storage implementation.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

from .db import DatabaseUnavailableError
from .models import validate_settings_update
from .storage import Storage

log = logging.getLogger("mathchecker.services")


class SettingsService:
    def __init__(self, storage: Storage):
        self.storage = storage

    def get(self) -> dict[str, Any]:
        return self.storage.get_settings()

    def update(self, changes: Mapping[str, Any]) -> dict[str, Any]:
        validated = validate_settings_update(changes)
        previous = self.storage.get_settings()
        updated = self.storage.update_settings(validated)
        changed = sorted(
            key for key, value in validated.items() if previous.get(key) != value
        )
        if changed:
            # Key names only: values are never written to logs.
            log.info("settings updated: %s", ", ".join(changed))
        return updated


class StatsService:
    def __init__(self, storage: Storage):
        self.storage = storage

    def snapshot(self) -> dict[str, Any]:
        status = self.storage.database_status()
        if not status.ready:
            raise DatabaseUnavailableError(
                status.detail or "The local database is not available."
            )
        stats = self.storage.stats()
        return {
            "database": {
                "status": "ready",
                "schema_version": status.schema_version,
            },
            "counts": stats.as_counts(),
        }
