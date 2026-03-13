"""Async database engine and session factory for Purveyor."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import purveyor.models.tables as _tables  # noqa: F401 — side-effect: registers ORM models with Base.metadata
from purveyor.models.base import Base


def create_engine(database_url: str, echo: bool = False) -> AsyncEngine:
    """Create an async SQLAlchemy engine for the given database URL.

    Handles both SQLite (aiosqlite) and Postgres (asyncpg) URLs.

    Args:
        database_url: SQLAlchemy-style async database URL.
        echo: If True, log all SQL statements (useful for debugging).
    """
    if database_url.startswith("sqlite"):
        # SQLite-specific: disable connection pooling for async (StaticPool for :memory:)
        from sqlalchemy.pool import StaticPool

        if ":memory:" in database_url:
            return create_async_engine(
                database_url,
                echo=echo,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
        return create_async_engine(
            database_url,
            echo=echo,
            connect_args={"check_same_thread": False},
        )

    return create_async_engine(database_url, echo=echo)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create an async session factory bound to the given engine."""
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )


async def init_db(engine: AsyncEngine) -> None:
    """Initialize the database schema.

    For SQLite databases — both in-memory (``:memory:``) and file-based — this
    calls ``Base.metadata.create_all`` directly from the ORM models.  In-memory
    SQLite is used by tests and the demo agent subprocess; file-based SQLite
    (``purveyor.db``) is used for local single-user development.

    Alembic migrations cannot target an ephemeral ``:memory:`` connection, and
    requiring ``alembic upgrade head`` before every ``purveyor demo`` run would
    be a poor local-dev experience.  ``create_all`` is idempotent — it skips
    tables that already exist — so it is safe to call on a DB that was already
    set up by Alembic.

    For Postgres, this function is a no-op.  Always run ``alembic upgrade head``
    before starting the server against a Postgres database.
    """
    url = str(engine.url)
    if ":memory:" in url or url.startswith("sqlite"):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)


async def get_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yield a database session and close it on exit."""
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
