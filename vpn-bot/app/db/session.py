from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings
from app.utils.logging import get_logger

log = get_logger(__name__)

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def is_sqlite() -> bool:
    return settings.database_url.startswith("sqlite")


def _prepare_sqlite_path() -> None:
    url = settings.database_url
    marker = ":///"
    if marker not in url:
        return
    file_path = url.split(marker, 1)[1].split("?", 1)[0]
    if file_path and file_path != ":memory:":
        Path(file_path).expanduser().parent.mkdir(parents=True, exist_ok=True)


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is not None:
        return _engine

    if is_sqlite():
        _prepare_sqlite_path()
        _engine = create_async_engine(
            settings.database_url,
            echo=False,
            pool_pre_ping=True,
            connect_args={"timeout": 30},
        )

        @event.listens_for(_engine.sync_engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record) -> None:  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()
    else:
        _engine = create_async_engine(
            settings.database_url,
            echo=False,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
        )
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            autoflush=False,
        )
    return _sessionmaker


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Сессия с коммитом на выходе и откатом при исключении."""
    factory = get_sessionmaker()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def lock_row(session: AsyncSession, table: str, row_id: int) -> None:
    """SELECT ... FOR UPDATE в PostgreSQL. В SQLite блокировка на уровне файла/NamedLocks."""
    if is_sqlite():
        return
    await session.execute(
        text(f"SELECT id FROM {table} WHERE id = :id FOR UPDATE"),  # noqa: S608 - table из кода
        {"id": row_id},
    )


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        log.info("DB engine закрыт")
    _engine = None
    _sessionmaker = None
