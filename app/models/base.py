"""SQLAlchemy declarative base and shared column mixins."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, MetaData, TypeDecorator
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Explicit naming convention keeps Alembic autogenerate stable across SQLite
# and PostgreSQL (SQLite otherwise produces unnamed constraints).
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utc_now() -> datetime:
    """Timezone aware ``now`` used as the default for timestamp columns."""
    return datetime.now(UTC)


class UtcDateTime(TypeDecorator[datetime]):
    """A timestamp column that is always UTC and always timezone aware.

    ``DateTime(timezone=True)`` is a *request* to the database, not a promise.
    PostgreSQL honours it and returns an aware value; SQLite has no timestamp
    type at all and hands back a naive one. The same API therefore served
    ``2026-08-01T01:43:18`` locally and ``2026-08-01T01:43:18+00:00`` in
    production - and a browser reads the first as *local* time, so a report
    created a minute ago displays an hour or two in the future depending on
    where the reader is sitting.

    This decorator removes the difference at the one place it can be removed
    once: values going in are converted to UTC, values coming back out get
    ``timezone.utc`` attached when the driver dropped it. The underlying column
    type is unchanged (``TIMESTAMP WITH TIME ZONE`` where that exists), so no
    migration is needed and existing rows keep working - they were UTC all
    along, they just stopped saying so.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> datetime | None:
        """Store every timestamp as UTC."""
        if value is None:
            return None
        if not isinstance(value, datetime):  # pragma: no cover - guarded by typing
            raise TypeError(f"expected a datetime, got {type(value).__name__}")
        if value.tzinfo is None:
            # A naive value reaching the database is assumed to be UTC, which is
            # what every writer in this project produces (`utc_now`).
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: Any, dialect: Dialect) -> datetime | None:
        """Return every timestamp as an aware UTC value."""
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class Base(DeclarativeBase):
    """Declarative base for every ORM model in the project."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    """Adds ``created_at`` / ``updated_at`` columns."""

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), default=utc_now, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )
