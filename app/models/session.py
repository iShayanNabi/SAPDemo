"""Database engine and session management.

The engine is built from ``settings.database_url``. SQLite gets the extra
arguments it needs for use inside FastAPI; every other URL (PostgreSQL in
particular) is used unchanged, so switching databases is a one line change in
``.env``.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.logging import get_logger
from app.models.base import Base

logger = get_logger(__name__)


def _engine_kwargs(database_url: str) -> dict[str, Any]:
    """Return engine kwargs appropriate for the configured database."""
    if database_url.startswith("sqlite"):
        return {
            # FastAPI may touch a session from a different thread than the one
            # that created it; SQLite needs to be told this is acceptable.
            "connect_args": {"check_same_thread": False},
            "pool_pre_ping": True,
        }
    # PostgreSQL / other server databases.
    return {"pool_pre_ping": True, "pool_size": 5, "max_overflow": 10}


engine: Engine = create_engine(
    settings.database_url,
    echo=settings.database_echo,
    future=True,
    **_engine_kwargs(settings.database_url),
)


@event.listens_for(Engine, "connect")
def _set_sqlite_pragmas(dbapi_connection: Any, _connection_record: Any) -> None:
    """Enable foreign keys on SQLite (off by default) - no-op elsewhere."""
    module_name = type(dbapi_connection).__module__
    if "sqlite" in module_name:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_db() -> None:
    """Create tables that do not exist yet.

    Convenient for local development and tests. Alembic migrations remain the
    source of truth for anything beyond a throwaway local database.
    """
    # Importing the package registers every module's ORM models on the shared
    # metadata. Importing one module by name would silently skip the others.
    import app.models  # noqa: F401  (side-effect import)

    Base.metadata.create_all(bind=engine)
    logger.info("Database schema ensured for %s", _safe_db_label())


def _safe_db_label() -> str:
    """Return a log-safe database label (never includes credentials)."""
    url = settings.database_url
    return url.split("://", 1)[0] if "://" in url else "database"


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Context manager providing a transactional session for scripts/services."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
