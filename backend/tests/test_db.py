"""Tests for fresh initialization, PRAGMAs and the migration runner."""

from __future__ import annotations

import pytest

from app.db import (
    CURRENT_SCHEMA_VERSION,
    REQUIRED_TABLES,
    Database,
    SchemaTooNewError,
    migration_files,
)
from app.storage import Storage


def test_fresh_database_initializes_to_current_schema(tmp_path):
    db = Database(tmp_path / "app.db")
    assert db.initialize() == CURRENT_SCHEMA_VERSION

    with db.connection() as conn:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert REQUIRED_TABLES <= tables
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA user_version").fetchone()[0] == CURRENT_SCHEMA_VERSION


def test_migrations_are_numbered_and_ordered():
    migrations = migration_files()
    assert migrations
    assert [version for version, _ in migrations] == sorted(
        version for version, _ in migrations
    )
    assert migrations[0][0] == 1


def test_initialize_is_idempotent_and_preserves_data(tmp_path):
    db = Database(tmp_path / "app.db")
    db.initialize()
    storage = Storage(db)
    student = storage.create_student("Ada Lovelace", external_id="ada")

    assert db.initialize() == CURRENT_SCHEMA_VERSION
    assert storage.get_student(student.id) == student
    assert db.status().ready is True


def test_newer_schema_is_reported_and_not_overwritten(tmp_path):
    db = Database(tmp_path / "app.db")
    db.initialize()
    storage = Storage(db)
    student = storage.create_student("Grace Hopper")

    with db.connection() as conn:
        conn.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION + 1}")

    with pytest.raises(SchemaTooNewError):
        db.initialize()

    status = db.status()
    assert status.ready is False
    assert status.schema_version == CURRENT_SCHEMA_VERSION + 1
    assert "newer" in (status.detail or "").lower()
    # The original data was not destroyed by the refused migration.
    assert storage.get_student(student.id) is not None


def test_uninitialized_database_is_not_ready(tmp_path):
    db = Database(tmp_path / "app.db")
    status = db.status()
    assert status.ready is False
    assert status.schema_version == 0
    assert "not initialized" in (status.detail or "").lower()


def test_missing_table_is_reported_as_incomplete(tmp_path):
    db = Database(tmp_path / "app.db")
    db.initialize()
    with db.connection() as conn:
        conn.execute("DROP TABLE correction_results")
    status = db.status()
    assert status.ready is False
    assert "incomplete" in (status.detail or "").lower()


def test_database_status_never_raises_for_an_unusable_path(tmp_path):
    bad_path = tmp_path / "not-a-database"
    bad_path.mkdir()
    status = Database(bad_path).status()
    assert status.ready is False
    assert status.detail
    assert str(bad_path) not in (status.detail or "")
