"""Alembic environment.

URL берётся из `settings.database_url`, а не из alembic.ini — один источник
истины и никаких кредов в репозитории.

Работает и с SQLite (dev), и с PostgreSQL (prod):
- `render_as_batch=True` нужен SQLite, где нет полноценного ALTER TABLE;
- движок асинхронный, поэтому миграции идут через `run_sync`.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import AsyncEngine

# Импорт моделей обязателен: без него Base.metadata пустая и autogenerate
# сгенерирует миграцию на удаление всех таблиц.
import app.db.models  # noqa: F401
from app.config import settings
from app.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    """URL из -x db_url=..., иначе из настроек приложения."""
    return context.get_x_argument(as_dictionary=True).get("db_url") or settings.database_url


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def run_migrations_offline() -> None:
    """Генерация SQL без подключения к БД (`alembic upgrade head --sql`)."""
    url = _database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        render_as_batch=_is_sqlite(url),
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection) -> None:  # type: ignore[no-untyped-def]
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    from app.db.session import create_engine

    connectable: AsyncEngine = create_engine(_database_url())
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(_do_run_migrations)
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(_run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
