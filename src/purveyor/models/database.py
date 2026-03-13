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
    """Create all tables in the database.

    For production deployments, use Alembic migrations instead.
    This is useful for tests and local SQLite setup.
    """
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
