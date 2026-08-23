"""Общие фикстуры.

Переменные окружения выставляются ДО импорта app.config, иначе Settings
упадёт на обязательных bot_token/secret_key.
"""

from __future__ import annotations

import os

from cryptography.fernet import Fernet

os.environ.setdefault("BOT_TOKEN", "123456:test-token")
os.environ.setdefault("SECRET_KEY", Fernet.generate_key().decode())
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.base import Base
from app.db.repositories import UnitOfWork


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Чистая БД на каждый тест.

    StaticPool + один connection: у `:memory:` база живёт внутри соединения,
    поэтому обычный пул отдал бы каждому запросу пустую БД.
    """
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import StaticPool

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with factory() as s:
        yield s

    await engine.dispose()


@pytest_asyncio.fixture
async def uow(session: AsyncSession) -> UnitOfWork:
    return UnitOfWork(session)
