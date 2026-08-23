from __future__ import annotations

from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Subscription, SubscriptionStatus, User
from app.utils.time import utcnow


async def get(session: AsyncSession, subscription_id: int) -> Subscription | None:
    return await session.get(Subscription, subscription_id)


async def get_owned(
    session: AsyncSession, subscription_id: int, user_id: int
) -> Subscription | None:
    """Всегда проверяем владельца — защита от подделки id в callback_data."""
    subscription = await session.get(Subscription, subscription_id)
    if subscription is None or subscription.user_id != user_id:
        return None
    return subscription


async def get_by_email(session: AsyncSession, email: str) -> Subscription | None:
    result = await session.execute(select(Subscription).where(Subscription.xui_email == email))
    return result.scalar_one_or_none()


async def get_by_uuid(session: AsyncSession, uuid: str) -> Subscription | None:
    result = await session.execute(
        select(Subscription).where(Subscription.xui_client_uuid == uuid)
    )
    return result.scalar_one_or_none()


async def list_for_user(
    session: AsyncSession, user: User, include_deleted: bool = False
) -> list[Subscription]:
    stmt = select(Subscription).where(Subscription.user_id == user.id)
    if not include_deleted:
        stmt = stmt.where(Subscription.status != SubscriptionStatus.deleted)
    result = await session.execute(stmt.order_by(Subscription.expires_at.desc()))
    return list(result.scalars())


async def has_active(session: AsyncSession, user: User) -> bool:
    result = await session.execute(
        select(Subscription.id)
        .where(
            Subscription.user_id == user.id,
            Subscription.status == SubscriptionStatus.active,
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def newest_active_for_server(
    session: AsyncSession, user: User, server_id: int
) -> Subscription | None:
    result = await session.execute(
        select(Subscription)
        .where(
            Subscription.user_id == user.id,
            Subscription.server_id == server_id,
            Subscription.status.in_(
                [SubscriptionStatus.active, SubscriptionStatus.expired, SubscriptionStatus.disabled]
            ),
        )
        .order_by(Subscription.expires_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_active(session: AsyncSession) -> list[Subscription]:
    result = await session.execute(
        select(Subscription)
        .where(Subscription.status == SubscriptionStatus.active)
        .order_by(Subscription.id)
    )
    return list(result.scalars())


async def list_expired_unprocessed(session: AsyncSession) -> list[Subscription]:
    result = await session.execute(
        select(Subscription).where(
            Subscription.status == SubscriptionStatus.active,
            Subscription.expires_at <= utcnow(),
        )
    )
    return list(result.scalars())


async def list_expiring_soon(session: AsyncSession) -> list[Subscription]:
    horizon = utcnow() + timedelta(days=3)
    result = await session.execute(
        select(Subscription).where(
            Subscription.status == SubscriptionStatus.active,
            Subscription.expires_at <= horizon,
            or_(
                Subscription.notified_3d.is_(False),
                Subscription.notified_1d.is_(False),
                Subscription.notified_3h.is_(False),
            ),
        )
    )
    return list(result.scalars())


async def list_for_cleanup(session: AsyncSession, older_than_days: int) -> list[Subscription]:
    threshold = utcnow() - timedelta(days=older_than_days)
    result = await session.execute(
        select(Subscription).where(
            Subscription.status.in_([SubscriptionStatus.expired, SubscriptionStatus.disabled]),
            Subscription.expires_at <= threshold,
        )
    )
    return list(result.scalars())
