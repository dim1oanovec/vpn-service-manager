from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.db.models import Subscription, SubscriptionStatus
from app.db.repositories.base import BaseRepository
from app.utils.time import extend_from, utcnow


class SubscriptionRepository(BaseRepository[Subscription]):
    model = Subscription

    # ---------- выборки ----------

    async def get_with_relations(self, subscription_id: int) -> Subscription | None:
        stmt = (
            select(Subscription)
            .where(Subscription.id == subscription_id)
            .options(
                selectinload(Subscription.server),
                selectinload(Subscription.plan),
                selectinload(Subscription.user),
            )
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def get_by_email(self, xui_email: str) -> Subscription | None:
        stmt = select(Subscription).where(Subscription.xui_email == xui_email)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_uuid(self, client_uuid: str) -> Subscription | None:
        stmt = select(Subscription).where(Subscription.xui_client_uuid == client_uuid)
        return (await self.session.execute(stmt)).scalars().first()

    async def list_for_user(
        self, user_id: int, *, include_deleted: bool = False
    ) -> list[Subscription]:
        conditions = [Subscription.user_id == user_id]
        if not include_deleted:
            conditions.append(Subscription.status != SubscriptionStatus.deleted)
        stmt = (
            select(Subscription)
            .where(*conditions)
            .options(selectinload(Subscription.server), selectinload(Subscription.plan))
            .order_by(Subscription.expires_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_active_for_user(self, user_id: int) -> list[Subscription]:
        stmt = (
            select(Subscription)
            .where(
                Subscription.user_id == user_id,
                Subscription.status == SubscriptionStatus.active,
                Subscription.expires_at > utcnow(),
            )
            .options(selectinload(Subscription.server), selectinload(Subscription.plan))
            .order_by(Subscription.expires_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def has_active(self, user_id: int) -> bool:
        return await self.exists(
            Subscription.user_id == user_id,
            Subscription.status == SubscriptionStatus.active,
            Subscription.expires_at > utcnow(),
        )

    async def search(self, query: str, limit: int = 20) -> list[Subscription]:
        """Админский поиск по email или uuid клиента (§9 ТЗ)."""
        query = query.strip()
        if not query:
            return []
        stmt = (
            select(Subscription)
            .where(
                or_(
                    Subscription.xui_email.ilike(f"%{query}%"),
                    Subscription.xui_client_uuid.ilike(f"%{query}%"),
                )
            )
            .options(selectinload(Subscription.server), selectinload(Subscription.user))
            .order_by(Subscription.id.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    # ---------- выборки для фоновых задач (§8 ТЗ) ----------

    async def list_for_traffic_sync(self, limit: int = 500) -> list[Subscription]:
        stmt = (
            select(Subscription)
            .where(
                Subscription.status.in_(
                    (SubscriptionStatus.active, SubscriptionStatus.disabled)
                )
            )
            .options(selectinload(Subscription.server))
            .order_by(
                # Сначала те, что синхронизировались давнее всего.
                Subscription.last_synced_at.is_(None).desc(),
                Subscription.last_synced_at.asc(),
            )
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_just_expired(self, limit: int = 200) -> list[Subscription]:
        stmt = (
            select(Subscription)
            .where(
                Subscription.status == SubscriptionStatus.active,
                Subscription.expires_at <= utcnow(),
            )
            .options(selectinload(Subscription.server))
            .order_by(Subscription.expires_at.asc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_expiring_within(
        self, delta: timedelta, flag_column: str, limit: int = 200
    ) -> list[Subscription]:
        """Кандидаты на напоминание: истекают в пределах `delta` и флаг ещё не выставлен."""
        flag = getattr(Subscription, flag_column)
        now = utcnow()
        stmt = (
            select(Subscription)
            .where(
                Subscription.status == SubscriptionStatus.active,
                Subscription.expires_at > now,
                Subscription.expires_at <= now + delta,
                flag.is_(False),
            )
            .options(selectinload(Subscription.plan), selectinload(Subscription.server))
            .order_by(Subscription.expires_at.asc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_stale_expired(self, older_than_days: int, limit: int = 200) -> list[Subscription]:
        """Истекли давно — пора удалять клиента из панели (`cleanup_deleted`)."""
        threshold = utcnow() - timedelta(days=older_than_days)
        stmt = (
            select(Subscription)
            .where(
                Subscription.status.in_(
                    (SubscriptionStatus.expired, SubscriptionStatus.disabled)
                ),
                Subscription.expires_at <= threshold,
            )
            .options(selectinload(Subscription.server))
            .order_by(Subscription.expires_at.asc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_by_server(
        self, server_id: int, *, only_alive: bool = True
    ) -> list[Subscription]:
        """Для сверки БД ↔ панель (`reconcile_panel`)."""
        conditions = [Subscription.server_id == server_id]
        if only_alive:
            conditions.append(Subscription.status != SubscriptionStatus.deleted)
        return await self.list(*conditions, order_by=Subscription.id)

    # ---------- мутации ----------

    async def extend(self, subscription: Subscription, days: int) -> datetime:
        """Продление: от текущей даты, если она в будущем, иначе от now (§5.3 ТЗ)."""
        subscription.expires_at = extend_from(subscription.expires_at, days)
        subscription.status = SubscriptionStatus.active
        subscription.reset_notifications()
        await self.session.flush()
        return subscription.expires_at

    async def set_status(
        self, subscription: Subscription, status: SubscriptionStatus
    ) -> None:
        subscription.status = status
        await self.session.flush()

    async def update_traffic(self, subscription: Subscription, used_bytes: int) -> None:
        subscription.traffic_used_bytes = max(int(used_bytes or 0), 0)
        subscription.last_synced_at = utcnow()

    async def can_reissue(self, subscription: Subscription, cooldown_hours: int) -> bool:
        """Перевыпуск ключа не чаще одного раза в N часов (§5.3 ТЗ)."""
        if cooldown_hours <= 0 or subscription.last_reissued_at is None:
            return True
        last = subscription.last_reissued_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=utcnow().tzinfo)
        return utcnow() - last >= timedelta(hours=cooldown_hours)

    async def apply_reissue(
        self, subscription: Subscription, new_uuid: str, new_sub_id: str
    ) -> None:
        subscription.xui_client_uuid = new_uuid
        subscription.xui_sub_id = new_sub_id
        subscription.last_reissued_at = utcnow()
        await self.session.flush()

    # ---------- статистика ----------

    async def count_active(self) -> int:
        return await self.count(
            Subscription.status == SubscriptionStatus.active,
            Subscription.expires_at > utcnow(),
        )

    async def count_by_plan(self) -> dict[int, int]:
        stmt = (
            select(Subscription.plan_id, func.count())
            .where(
                Subscription.status == SubscriptionStatus.active,
                Subscription.expires_at > utcnow(),
            )
            .group_by(Subscription.plan_id)
        )
        return {
            int(plan_id): int(count)
            for plan_id, count in (await self.session.execute(stmt)).all()
        }


__all__ = ["SubscriptionRepository"]
