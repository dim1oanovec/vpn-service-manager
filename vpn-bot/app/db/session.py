from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

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


def _ensure_sqlite_dir(url: str) -> None:
    if not url.startswith("sqlite"):
        return
    path = url.split("///")[-1]
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        url = settings.database_url
        _ensure_sqlite_dir(url)
        is_sqlite = url.startswith("sqlite")
        _engine = create_async_engine(
            url,
            echo=False,
            pool_pre_ping=not is_sqlite,
            connect_args={"timeout": 30} if is_sqlite else {},
        )
        if is_sqlite:

            @event.listens_for(_engine.sync_engine, "connect")
            def _sqlite_pragmas(dbapi_conn, _record) -> None:  # type: ignore[no-untyped-def]
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA busy_timeout=30000")
                cursor.close()

        log.info("DB engine создан (%s)", "sqlite" if is_sqlite else "postgres")
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
    """Сессия с автокоммитом/откатом — для задач планировщика и веб-хуков."""
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def lock_row(session: AsyncSession, table: str, row_id: int) -> None:
    """SELECT ... FOR UPDATE для Postgres. На SQLite полагаемся на named_locks + WAL."""
    if session.bind is None or session.bind.dialect.name != "postgresql":
        return
    await session.execute(
        text(f"SELECT id FROM {table} WHERE id = :id FOR UPDATE"), {"id": row_id}
    )


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        log.info("DB engine закрыт")
    _engine = None
    _sessionmaker = None
