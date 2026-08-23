"""Async engine и фабрика сессий.

Поддерживаются два бэкенда через `DATABASE_URL`:
- dev:  sqlite+aiosqlite:///./data/bot.db
- prod: postgresql+asyncpg://user:pass@host/db

Для SQLite дополнительно включаются `foreign_keys=ON` (иначе FK молча игнорируются)
и WAL — без этого конкурентные записи планировщика и хендлеров дают "database is locked".
"""

from __future__ import annotations

import logging
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
from sqlalchemy.pool import NullPool

from app.config import settings

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def _ensure_sqlite_dir(url: str) -> None:
    """SQLite не создаёт каталог сам — при `sqlite+aiosqlite:///./data/bot.db` упадёт."""
    _, _, path_part = url.partition(":///")
    path_part = path_part.split("?", 1)[0]
    if not path_part or path_part == ":memory:":
        return
    parent = Path(path_part).expanduser().parent
    if parent and not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)


def _apply_sqlite_pragmas(engine: AsyncEngine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragmas(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
        finally:
            cursor.close()


def create_engine(url: str | None = None, **kwargs: object) -> AsyncEngine:
    """Создаёт engine с параметрами, подходящими выбранному бэкенду."""
    database_url = url or settings.database_url
    options: dict[str, object] = {
        "echo": False,
        "future": True,
        "pool_pre_ping": True,
    }

    if _is_sqlite(database_url):
        _ensure_sqlite_dir(database_url)
        # У aiosqlite нет реального пула соединений — NullPool избавляет от
        # "SQLite objects created in a thread..." при работе из разных задач.
        options["poolclass"] = NullPool
        options.pop("pool_pre_ping", None)
    else:
        options["pool_size"] = 10
        options["max_overflow"] = 20
        options["pool_recycle"] = 1800

    options.update(kwargs)
    engine = create_async_engine(database_url, **options)  # type: ignore[arg-type]

    if _is_sqlite(database_url):
        _apply_sqlite_pragmas(engine)

    return engine


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_engine()
        logger.info("db engine initialized (%s)", _engine.dialect.name)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,  # объекты остаются доступны после commit
            autoflush=False,
        )
    return _sessionmaker


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Транзакционная сессия для фоновых задач, CLI и вебхуков.

    Хендлеры бота сессию не создают — её прокидывает DbSessionMiddleware.
    """
    factory = get_sessionmaker()
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def healthcheck() -> bool:
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:  # pragma: no cover - диагностика в /healthz
        logger.exception("db healthcheck failed")
        return False


async def dispose_engine() -> None:
    """Graceful shutdown (§10 ТЗ)."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        logger.info("db engine disposed")
    _engine = None
    _sessionmaker = None


def supports_row_locks() -> bool:
    """`SELECT ... FOR UPDATE` есть в PostgreSQL, но не в SQLite (§6.4 ТЗ)."""
    return not _is_sqlite(settings.database_url)


__all__ = [
    "create_engine",
    "dispose_engine",
    "get_engine",
    "get_sessionmaker",
    "healthcheck",
    "session_scope",
    "supports_row_locks",
]
