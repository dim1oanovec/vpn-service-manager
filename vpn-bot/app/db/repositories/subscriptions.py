from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Subscription, SubscriptionStatus
from app.utils.time import utcnow


class SubscriptionsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def by_id(self, subscription_id: int) -> Subscription | None:
        return await self.session.get(Subscription, subscription_id)

    async def by_email(self, email: str) -> Subscription | None:
        result = await self.session.execute(
            select(Subscription).where(Subscription.xui_email == email)
        )
        return result.scalar_one_or_none()

    async def by_uuid(self, uuid: str) -> Subscription | None:
        result = await self.session.execute(
            select(Subscription).where(Subscription.xui_client_uuid == uuid)
        )
        return result.scalar_one_or_none()

    async def of_user(
        self, user_id: int, include_deleted: bool = False
    ) -> list[Subscription]:
        stmt = select(Subscription).where(Subscription.user_id == user_id)
        if not include_deleted:
            stmt = stmt.where(Subscription.status != SubscriptionStatus.deleted)
        stmt = stmt.order_by(Subscription.expires_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars())

    async def active_of_user(self, user_id: int) -> list[Subscription]:
        result = await self.session.execute(
            select(Subscription)
            .where(
                Subscription.user_id == user_id,
                Subscription.status == SubscriptionStatus.active,
                Subscription.expires_at > utcnow(),
            )
            .order_by(Subscription.expires_at.desc())
        )
        return list(result.scalars())

    async def has_active(self, user_id: int) -> bool:
        return bool(await self.active_of_user(user_id))

    async def create(
        self,
        *,
        user_id: int,
        server_id: int,
        plan_id: int,
        xui_client_uuid: str,
        xui_email: str,
        xui_sub_id: str,
        xui_inbound_id: int,
        expires_at: datetime,
    ) -> Subscription:
        subscription = Subscription(
            user_id=user_id,
            server_id=server_id,
            plan_id=plan_id,
            xui_client_uuid=xui_client_uuid,
            xui_email=xui_email,
            xui_sub_id=xui_sub_id,
            xui_inbound_id=xui_inbound_id,
            status=SubscriptionStatus.active,
            started_at=utcnow(),
            expires_at=expires_at,
        )
        self.session.add(subscription)
        await self.session.flush()
        return subscription

    async def all_active(self) -> list[Subscription]:
        result = await self.session.execute(
            select(Subscription).where(Subscription.status == SubscriptionStatus.active)
        )
        return list(result.scalars())

    async def due_to_expire(self) -> list[Subscription]:
        result = await self.session.execute(
            select(Subscription).where(
                Subscription.status == SubscriptionStatus.active,
                Subscription.expires_at <= utcnow(),
            )
        )
        return list(result.scalars())

    async def expiring_before(self, until: datetime) -> list[Subscription]:
        result = await self.session.execute(
            select(Subscription).where(
                Subscription.status == SubscriptionStatus.active,
                Subscription.expires_at > utcnow(),
                Subscription.expires_at <= until,
            )
        )
        return list(result.scalars())

    async def expired_before(self, days: int) -> list[Subscription]:
        threshold = utcnow() - timedelta(days=days)
        result = await self.session.execute(
            select(Subscription).where(
                Subscription.status.in_(
                    [SubscriptionStatus.expired, SubscriptionStatus.disabled]
                ),
                Subscription.expires_at <= threshold,
            )
        )
        return list(result.scalars())

    async def count_active(self) -> int:
        result = await self.session.execute(
            select(func.count(Subscription.id)).where(
                Subscription.status == SubscriptionStatus.active,
                Subscription.expires_at > utcnow(),
            )
        )
        return int(result.scalar_one())

    async def count_active_by_server(self) -> list[tuple[int, int]]:
        result = await self.session.execute(
            select(Subscription.server_id, func.count(Subscription.id))
            .where(Subscription.status == SubscriptionStatus.active)
            .group_by(Subscription.server_id)
        )
        return [(int(server_id), int(count)) for server_id, count in result.all()]

    async def count_by_plan(self) -> list[tuple[int, int]]:
        result = await self.session.execute(
            select(Subscription.plan_id, func.count(Subscription.id))
            .where(Subscription.status == SubscriptionStatus.active)
            .group_by(Subscription.plan_id)
        )
        return [(int(plan_id), int(count)) for plan_id, count in result.all()]

    async def all_emails(self) -> set[str]:
        result = await self.session.execute(
            select(Subscription.xui_email).where(
                Subscription.status != SubscriptionStatus.deleted
            )
        )
        return set(result.scalars())
