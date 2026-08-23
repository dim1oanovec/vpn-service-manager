"""Агрегатор репозиториев (Unit of Work).

Собирает все репозитории вокруг ОДНОЙ `AsyncSession`, чтобы вызывающий код
не создавал их по отдельности и не рисковал смешать сессии в одной операции.

Транзакцией владеет вызывающий код, а не UoW и не репозитории (см. `base.py`):
- хендлеры бота  -> сессию прокидывает `DbSessionMiddleware`;
- задачи и CLI   -> `async with session_scope() as s: uow = UnitOfWork(s)`.

Репозитории создаются лениво и кешируются: в одном апдейте обычно нужны
2-3 репозитория из 10, а не все сразу.

Пример::

    async with session_scope() as session:
        uow = UnitOfWork(session)
        user = await uow.users.get_or_create(tg_id=42)
        await uow.audit.log(user_id=user.id, action="start")
    # commit делает session_scope
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.audit import AuditRepository, JobLockRepository
from app.db.repositories.base import (
    BaseRepository,
    InsufficientBalanceError,
    RepositoryError,
)
from app.db.repositories.payments import PaymentRepository
from app.db.repositories.plans import PlanRepository
from app.db.repositories.promo import PromoRepository
from app.db.repositories.referrals import ReferralRepository
from app.db.repositories.servers import NoServerAvailableError, ServerRepository
from app.db.repositories.subscriptions import SubscriptionRepository
from app.db.repositories.tickets import TicketRepository
from app.db.repositories.users import UserRepository


class UnitOfWork:
    """Единая точка доступа к репозиториям в рамках одной сессии."""

    __slots__ = ("session", "_cache")

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._cache: dict[str, Any] = {}

    def _repo(self, key: str, factory: type) -> Any:
        repo = self._cache.get(key)
        if repo is None:
            repo = factory(self.session)
            self._cache[key] = repo
        return repo

    # ---------- репозитории ----------

    @property
    def users(self) -> UserRepository:
        return self._repo("users", UserRepository)

    @property
    def plans(self) -> PlanRepository:
        return self._repo("plans", PlanRepository)

    @property
    def servers(self) -> ServerRepository:
        return self._repo("servers", ServerRepository)

    @property
    def subscriptions(self) -> SubscriptionRepository:
        return self._repo("subscriptions", SubscriptionRepository)

    @property
    def payments(self) -> PaymentRepository:
        return self._repo("payments", PaymentRepository)

    @property
    def promo(self) -> PromoRepository:
        return self._repo("promo", PromoRepository)

    @property
    def referrals(self) -> ReferralRepository:
        return self._repo("referrals", ReferralRepository)

    @property
    def tickets(self) -> TicketRepository:
        return self._repo("tickets", TicketRepository)

    @property
    def audit(self) -> AuditRepository:
        return self._repo("audit", AuditRepository)

    @property
    def job_locks(self) -> JobLockRepository:
        return self._repo("job_locks", JobLockRepository)

    # ---------- работа с транзакцией ----------

    async def flush(self) -> None:
        """Отправить накопленные изменения в БД, не завершая транзакцию.

        Нужно, когда дальше требуется сгенерированный id.
        """
        await self.session.flush()

    async def commit(self) -> None:
        """Явный commit — для кода, который сам владеет транзакцией.

        Внутри `session_scope()` вызывать не нужно: он коммитит сам.
        """
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()


__all__ = [
    "AuditRepository",
    "BaseRepository",
    "InsufficientBalanceError",
    "JobLockRepository",
    "NoServerAvailableError",
    "PaymentRepository",
    "PlanRepository",
    "PromoRepository",
    "ReferralRepository",
    "RepositoryError",
    "ServerRepository",
    "SubscriptionRepository",
    "TicketRepository",
    "UnitOfWork",
    "UserRepository",
]
