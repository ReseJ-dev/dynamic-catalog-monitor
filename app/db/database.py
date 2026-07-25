"""Async SQLAlchemy engine, session, and schema helpers."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db.models import Base

SessionFactory = async_sessionmaker[AsyncSession]


def create_database_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    """Create an asynchronous SQLAlchemy engine for a database URL."""

    return create_async_engine(database_url, echo=echo)


def create_session_factory(engine: AsyncEngine) -> SessionFactory:
    """Create sessions that retain loaded values after a transaction commits."""

    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def initialize_database(engine: AsyncEngine) -> None:
    """Create all application tables if they do not already exist."""

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def session_context(session_factory: SessionFactory) -> AsyncIterator[AsyncSession]:
    """Yield a session and commit or roll back its transaction automatically."""

    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
