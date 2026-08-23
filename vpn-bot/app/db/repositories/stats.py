from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Payment,
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
    active_subs: int = 0
    expired_subs: int = 0
    revenue_day: int = 0
    revenue_week: int = 0
    revenue_month: int = 0
    mrr: int = 0
    trial_users: int = 0
    trial_converted: int = 0
    by_plan: list[tuple[str, int]] = field(default_factory=list)
    by_server: list[tuple[str, int]] = field(default_factory=list)

    @property
    def trial_conversion(self) -> float:
        if not self.trial_users:
            return 0.0
        return self.trial_converted / self.trial_users * 100


async def _revenue_since(session: AsyncSession, days: int) -> int:
    since = utcnow() - timedelta(days=days)
    value = await session.scalar(
        select(func.coalesce(func.sum(Payment.amount_kopeks), 0)).where(
            Payment.status == PaymentStatus.paid, Payment.paid_at >= since
        )
    )
    return int(value or 0)


async def collect(session: AsyncSession) -> Stats:
    stats = Stats()
    stats.users_total = int(await session.scalar(select(func.count(User.id))) or 0)
    stats.users_today = int(
        await session.scalar(
            select(func.count(User.id)).where(User.created_at >= utcnow() - timedelta(days=1))
        )
        or 0
    )
    stats.active_subs = int(
        await session.scalar(
            select(func.count(Subscription.id)).where(
                Subscription.status == SubscriptionStatus.active
            )
        )
        or 0
    )
    stats.expired_subs = int(
        await session.scalar(
            select(func.count(Subscription.id)).where(
                Subscription.status.in_([SubscriptionStatus.expired, SubscriptionStatus.disabled])
            )
        )
        or 0
    )
    stats.revenue_day = await _revenue_since(session, 1)
    stats.revenue_week = await _revenue_since(session, 7)
    stats.revenue_month = await _revenue_since(session, 30)

    # MRR: нормализуем стоимость активных подписок к 30 дням
    rows = await session.execute(
        select(Plan.price_kopeks, Plan.duration_days, func.count(Subscription.id))
        .join(Subscription, Subscription.plan_id == Plan.id)
        .where(Subscription.status == SubscriptionStatus.active, Plan.is_trial.is_(False))
        .group_by(Plan.price_kopeks, Plan.duration_days)
    )
    mrr = 0
    for price, duration, count in rows:
        if duration:
            mrr += int(price / duration * 30) * count
    stats.mrr = mrr

    stats.trial_users = int(
        await session.scalar(select(func.count(User.id)).where(User.trial_used.is_(True))) or 0
    )
    stats.trial_converted = int(
        await session.scalar(
            select(func.count(func.distinct(Payment.user_id))).where(
                Payment.status == PaymentStatus.paid,
                Payment.user_id.in_(select(User.id).where(User.trial_used.is_(True))),
            )
        )
        or 0
    )

    plan_rows = await session.execute(
        select(Plan.title, func.count(Subscription.id))
        .join(Subscription, Subscription.plan_id == Plan.id)
        .where(Subscription.status == SubscriptionStatus.active)
        .group_by(Plan.title)
        .order_by(func.count(Subscription.id).desc())
    )
    stats.by_plan = [(title, int(count)) for title, count in plan_rows]

    server_rows = await session.execute(
        select(Server.country_flag, Server.code, func.count(Subscription.id))
        .outerjoin(
            Subscription,
            (Subscription.server_id == Server.id)
            & (Subscription.status == SubscriptionStatus.active),
        )
        .group_by(Server.id)
        .order_by(Server.sort_order)
    )
    stats.by_server = [(f"{flag} {code}".strip(), int(count)) for flag, code, count in server_rows]
    return stats
