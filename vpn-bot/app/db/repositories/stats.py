from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Payment,
    PaymentProvider,
    PaymentStatus,
    Plan,
    Server,
    Subscription,
    SubscriptionStatus,
    User,
)
from app.utils.time import utcnow


@dataclass(slots=True)
class Stats:
    users_total: int = 0
    users_today: int = 0
    users_week: int = 0
    subs_active: int = 0
    subs_expired: int = 0
    revenue_day: int = 0
    revenue_week: int = 0
    revenue_month: int = 0
    mrr: int = 0
    trials_given: int = 0
    trials_converted: int = 0
    by_plan: list[tuple[str, int]] = field(default_factory=list)
    by_server: list[tuple[str, int]] = field(default_factory=list)

    @property
    def trial_conversion(self) -> float:
        if not self.trials_given:
            return 0.0
        return self.trials_converted / self.trials_given * 100


class StatsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _revenue_since(self, hours: int) -> int:
        since = utcnow() - timedelta(hours=hours)
        result = await self.session.execute(
            select(func.coalesce(func.sum(Payment.amount_kopeks), 0)).where(
                Payment.status == PaymentStatus.paid,
                Payment.paid_at >= since,
                Payment.provider != PaymentProvider.balance,
            )
        )
        return int(result.scalar_one())

    async def _mrr(self) -> int:
        """Нормализованная месячная выручка по активным подпискам."""
        result = await self.session.execute(
            select(Plan.price_kopeks, Plan.duration_days, func.count(Subscription.id))
            .join(Subscription, Subscription.plan_id == Plan.id)
            .where(
                Subscription.status == SubscriptionStatus.active,
                Plan.is_trial.is_(False),
            )
            .group_by(Plan.id, Plan.price_kopeks, Plan.duration_days)
        )
        total = 0.0
        for price, days, count in result.all():
            if not days:
                continue
            total += (price / days) * 30 * count
        return int(total)

    async def collect(self) -> Stats:
        stats = Stats()

        stats.users_total = int(
            (await self.session.execute(select(func.count(User.id)))).scalar_one()
        )
        stats.users_today = int(
            (
                await self.session.execute(
                    select(func.count(User.id)).where(
                        User.created_at >= utcnow() - timedelta(days=1)
                    )
                )
            ).scalar_one()
        )
        stats.users_week = int(
            (
                await self.session.execute(
                    select(func.count(User.id)).where(
                        User.created_at >= utcnow() - timedelta(days=7)
                    )
                )
            ).scalar_one()
        )

        stats.subs_active = int(
            (
                await self.session.execute(
                    select(func.count(Subscription.id)).where(
                        Subscription.status == SubscriptionStatus.active
                    )
                )
            ).scalar_one()
        )
        stats.subs_expired = int(
            (
                await self.session.execute(
                    select(func.count(Subscription.id)).where(
                        Subscription.status == SubscriptionStatus.expired
                    )
                )
            ).scalar_one()
        )

        stats.revenue_day = await self._revenue_since(24)
        stats.revenue_week = await self._revenue_since(24 * 7)
        stats.revenue_month = await self._revenue_since(24 * 30)
        stats.mrr = await self._mrr()

        stats.trials_given = int(
            (
                await self.session.execute(
                    select(func.count(User.id)).where(User.trial_used.is_(True))
                )
            ).scalar_one()
        )
        stats.trials_converted = int(
            (
                await self.session.execute(
                    select(func.count(func.distinct(Payment.user_id)))
                    .join(User, User.id == Payment.user_id)
                    .where(
                        Payment.status == PaymentStatus.paid,
                        Payment.amount_kopeks > 0,
                        User.trial_used.is_(True),
                    )
                )
            ).scalar_one()
        )

        by_plan = await self.session.execute(
            select(Plan.title, func.count(Subscription.id))
            .join(Subscription, Subscription.plan_id == Plan.id)
            .where(Subscription.status == SubscriptionStatus.active)
            .group_by(Plan.id, Plan.title)
            .order_by(func.count(Subscription.id).desc())
        )
        stats.by_plan = [(title, int(count)) for title, count in by_plan.all()]

        by_server = await self.session.execute(
            select(Server.code, func.count(Subscription.id))
            .join(Subscription, Subscription.server_id == Server.id)
            .where(Subscription.status == SubscriptionStatus.active)
            .group_by(Server.id, Server.code)
            .order_by(func.count(Subscription.id).desc())
        )
        stats.by_server = [(code, int(count)) for code, count in by_server.all()]

        return stats
