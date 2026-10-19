"""SQLite connection management and the schema migration runner.

The application uses the standard library only. Each operation opens its own
connection, which keeps sync FastAPI request threads independent while WAL
mode allows normal concurrent reads.

Migrations are numbered SQL files under ``app/migrations``. ``PRAGMA
user_version`` records the applied version. A database written by a newer
application is reported as unavailable instead of being modified.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .models import DatabaseStatus

log = logging.getLogger("mathchecker.db")

CURRENT_SCHEMA_VERSION = 1
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
REQUIRED_TABLES = frozenset(
    {"settings", "students", "assignments", "submissions", "correction_results"}
)


class DatabaseError(RuntimeError):
    """Base class for database lifecycle failures."""


class SchemaTooNewError(DatabaseError):
    """The database was written by a newer application version."""


class DatabaseUnavailableError(DatabaseError):
    """The database cannot serve the requested operation."""


class Database:
    """Owns one SQLite file and its schema lifecycle."""

    def __init__(self, path: Path | str):
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        """Open a configured connection. The caller is responsible for closing it."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Run a serialized write transaction (one SQLite writer at a time)."""
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def initialize(self) -> int:
        """Create or migrate the database to the current schema version.

        All migration scripts are idempotent DDL. The version marker is set
        only after a script succeeds, so a failed migration can be retried.
        """
        migrations = migration_files()
        if not migrations:
            raise DatabaseError("No database migrations were found.")

        with self.connection() as conn:
            version = _schema_version(conn)
            if version > CURRENT_SCHEMA_VERSION:
                raise SchemaTooNewError(
                    "The database schema is newer than this application version."
                )

            if version == CURRENT_SCHEMA_VERSION:
                _require_schema(conn)
                return version

            for target, path in migrations:
                if target <= version:
                    continue
                try:
                    script = path.read_text(encoding="utf-8")
                    conn.executescript(script)
                    conn.execute(f"PRAGMA user_version = {int(target)}")
                except (OSError, sqlite3.Error) as exc:
                    raise DatabaseError(f"Database migration {path.name} failed.") from exc
                version = target

            if version != CURRENT_SCHEMA_VERSION:
                raise DatabaseError("Database migrations did not reach the expected version.")
            _require_schema(conn)
            log.info("database ready (schema version %s)", version)
            return version

    def status(self) -> DatabaseStatus:
        """Return a safe readiness snapshot. Never raises for a broken database."""
        try:
            with self.connection() as conn:
                version = _schema_version(conn)
                if version > CURRENT_SCHEMA_VERSION:
                    return DatabaseStatus(
                        ready=False,
                        schema_version=version,
                        detail="Database schema is newer than this application version.",
                    )
                if version < CURRENT_SCHEMA_VERSION:
                    return DatabaseStatus(
                        ready=False,
                        schema_version=version,
                        detail="Database schema is not initialized.",
                    )
                if not REQUIRED_TABLES <= _table_names(conn):
                    return DatabaseStatus(
                        ready=False,
                        schema_version=version,
                        detail="Database schema is incomplete.",
                    )
                return DatabaseStatus(ready=True, schema_version=version)
        except (OSError, sqlite3.Error):
            log.exception("database status check failed")
            return DatabaseStatus(ready=False, detail="Database is unavailable.")


def migration_files() -> list[tuple[int, Path]]:
    """Return (version, path) pairs for numbered ``*.sql`` migration files."""
    found: list[tuple[int, Path]] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        prefix = path.name.split("_", 1)[0]
        if not prefix.isdigit():
            log.warning("Ignoring migration with no numeric prefix: %s", path.name)
            continue
        found.append((int(prefix), path))
    return found


def _schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0]) if row is not None else 0


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(row["name"]) for row in rows}


def _require_schema(conn: sqlite3.Connection) -> None:
    missing = REQUIRED_TABLES - _table_names(conn)
    if missing:
        raise DatabaseError(
            "Database schema is incomplete: " + ", ".join(sorted(missing))
        )
