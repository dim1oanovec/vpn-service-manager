"""Базовый репозиторий.

Репозитории НЕ коммитят — транзакцией владеет вызывающий код
(middleware для хендлеров, `session_scope()` для задач и CLI).
Это позволяет собирать несколько операций в одну атомарную транзакцию (§7 ТЗ).
"""

from __future__ import annotations

from typing import Any, Generic, Sequence, TypeVar

from sqlalchemy import Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base
from app.db.session import supports_row_locks

ModelT = TypeVar("ModelT", bound=Base)


class RepositoryError(Exception):
    """Базовая ошибка слоя доступа к данным."""


class InsufficientBalanceError(RepositoryError):
    """Списание с внутреннего баланса невозможно — не хватает средств."""


class BaseRepository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---------- чтение ----------

    async def get(self, pk: Any) -> ModelT | None:
        return await self.session.get(self.model, pk)

    async def get_for_update(self, pk: Any) -> ModelT | None:
        """Блокировка строки перед изменением. На SQLite деградирует до обычного get:
        там запись сериализуется на уровне файла (см. `supports_row_locks`)."""
        if not supports_row_locks():
            return await self.session.get(self.model, pk)
        stmt = select(self.model).where(self.model.id == pk).with_for_update()  # type: ignore[attr-defined]
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list(
        self,
        *whereclause: Any,
        order_by: Any = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[ModelT]:
        stmt: Select[tuple[ModelT]] = select(self.model)
        if whereclause:
            stmt = stmt.where(*whereclause)
        if order_by is not None:
            stmt = stmt.order_by(*(order_by if isinstance(order_by, (list, tuple)) else (order_by,)))
        if limit is not None:
            stmt = stmt.limit(limit)
        if offset:
            stmt = stmt.offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count(self, *whereclause: Any) -> int:
        stmt = select(func.count()).select_from(self.model)
        if whereclause:
            stmt = stmt.where(*whereclause)
        return int((await self.session.execute(stmt)).scalar_one())

    async def exists(self, *whereclause: Any) -> bool:
        stmt = select(self.model.id).where(*whereclause).limit(1)  # type: ignore[attr-defined]
        return (await self.session.execute(stmt)).first() is not None

    async def scalars(self, stmt: Select[Any]) -> Sequence[Any]:
        return (await self.session.execute(stmt)).scalars().all()

    # ---------- запись ----------

    def add(self, instance: ModelT) -> ModelT:
        self.session.add(instance)
        return instance

    async def create(self, **values: Any) -> ModelT:
        instance = self.model(**values)
        self.session.add(instance)
        await self.session.flush()
        return instance

    async def delete(self, instance: ModelT) -> None:
        await self.session.delete(instance)
        await self.session.flush()

    async def delete_where(self, *whereclause: Any) -> int:
        result = await self.session.execute(delete(self.model).where(*whereclause))
        return int(result.rowcount or 0)

    async def flush(self) -> None:
        await self.session.flush()


__all__ = ["BaseRepository", "ModelT"]
