"""The application database: engine, schema creation and transactions."""

from __future__ import annotations

import logging
from contextlib import AbstractContextManager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from cellsurvey.database.models import Base

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
"""Stored in SQLite's ``user_version``. Increase it with every schema change
and add the migration to :meth:`Database.create_schema`."""


class DatabaseError(Exception):
    """The database cannot be opened or is not usable by this version."""


class Database:
    """A SQLite database file."""

    def __init__(self, path: Path) -> None:
        """Open the database at ``path``, creating the file and its tables if needed.

        Raises:
            DatabaseError: the file cannot be opened, is not a database, or was
                written by a newer version of the application.
        """
        self.path = path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise DatabaseError(f"Cannot create {path.parent}: {exc}") from exc
        self._engine = create_engine(f"sqlite:///{path}")
        event.listen(self._engine, "connect", _enable_foreign_keys)
        self._sessions = sessionmaker(self._engine)
        try:
            self._create_schema()
        except DatabaseError:
            self._engine.dispose()
            raise
        except SQLAlchemyError as exc:
            self._engine.dispose()
            raise DatabaseError(f"Cannot open the database {path}: {exc}") from exc

    def session(self) -> AbstractContextManager[Session]:
        """A transaction: committed when the ``with`` block ends, rolled back if it raises."""
        return self._sessions.begin()

    def close(self) -> None:
        """Release the database file."""
        self._engine.dispose()

    def _create_schema(self) -> None:
        with self._engine.begin() as connection:
            version = connection.exec_driver_sql("PRAGMA user_version").scalar_one()
            if version > SCHEMA_VERSION:
                raise DatabaseError(
                    f"The database {self.path} was written by a newer version of the "
                    f"application (schema {version}; this version supports {SCHEMA_VERSION})."
                )
            Base.metadata.create_all(connection)
            connection.exec_driver_sql(f"PRAGMA user_version = {SCHEMA_VERSION}")
        logger.info(
            "Database opened", extra={"path": str(self.path), "schema_version": SCHEMA_VERSION}
        )


def _enable_foreign_keys(dbapi_connection: object, _record: object) -> None:
    """SQLite enforces foreign keys, and so cascades deletes, only when asked to."""
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.close()
