from __future__ import annotations

from functools import cached_property

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.audit import AuditRepo
from app.db.repositories.payments import PaymentsRepo
from app.db.repositories.plans import PlansRepo
from app.db.repositories.promo import PromoRepo
from app.db.repositories.servers import ServersRepo
from app.db.repositories.stats import StatsRepo
from app.db.repositories.subscriptions import SubscriptionsRepo
from app.db.repositories.support import SupportRepo
from app.db.repositories.users import UsersRepo


class Repos:
    """Единая точка доступа к репозиториям в рамках одной сессии."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @cached_property
    def users(self) -> UsersRepo:
        return UsersRepo(self.session)

    @cached_property
    def servers(self) -> ServersRepo:
        return ServersRepo(self.session)

    @cached_property
    def plans(self) -> PlansRepo:
        return PlansRepo(self.session)

    @cached_property
    def subscriptions(self) -> SubscriptionsRepo:
        return SubscriptionsRepo(self.session)

    @cached_property
    def payments(self) -> PaymentsRepo:
        return PaymentsRepo(self.session)

    @cached_property
    def promo(self) -> PromoRepo:
        return PromoRepo(self.session)

    @cached_property
    def audit(self) -> AuditRepo:
        return AuditRepo(self.session)

    @cached_property
    def support(self) -> SupportRepo:
        return SupportRepo(self.session)

    @cached_property
    def stats(self) -> StatsRepo:
        return StatsRepo(self.session)


__all__ = [
    "AuditRepo",
    "PaymentsRepo",
    "PlansRepo",
    "PromoRepo",
    "Repos",
    "ServersRepo",
    "StatsRepo",
    "SubscriptionsRepo",
    "SupportRepo",
    "UsersRepo",
]
