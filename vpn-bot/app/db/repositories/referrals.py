from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.db.models import Referral, User
from app.db.repositories.base import BaseRepository


class ReferralRepository(BaseRepository[Referral]):
    model = Referral

    async def get_by_payment(self, payment_id: int) -> Referral | None:
        """Уникальность по payment_id — защита от повторного начисления (§5.6 ТЗ)."""
        stmt = select(Referral).where(Referral.payment_id == payment_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def create_reward(
        self,
        *,
        referrer_id: int,
        referee_id: int,
        payment_id: int | None,
        reward_kopeks: int,
        paid: bool = False,
    ) -> Referral:
        referral = Referral(
            referrer_id=referrer_id,
            referee_id=referee_id,
            payment_id=payment_id,
            reward_kopeks=reward_kopeks,
            paid=paid,
        )
        self.session.add(referral)
        await self.session.flush()
        return referral

    async def mark_paid(self, referral: Referral) -> None:
        referral.paid = True
        await self.session.flush()

    async def list_for_referrer(self, referrer_id: int, limit: int = 20) -> list[Referral]:
        stmt = (
            select(Referral)
            .where(Referral.referrer_id == referrer_id)
            .options(selectinload(Referral.referee))
            .order_by(Referral.id.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def stats_for_referrer(self, referrer_id: int) -> dict[str, int]:
        """Сводка для экрана «Партнёрам»: приглашённые, платящие, заработано."""
        invited = int(
            (
                await self.session.execute(
                    select(func.count()).select_from(User).where(User.referrer_id == referrer_id)
                )
            ).scalar_one()
        )
        rows = (
            await self.session.execute(
                select(
                    func.count(func.distinct(Referral.referee_id)),
                    func.coalesce(func.sum(Referral.reward_kopeks), 0),
                ).where(Referral.referrer_id == referrer_id, Referral.paid.is_(True))
            )
        ).one()
        return {
            "invited": invited,
            "paying": int(rows[0] or 0),
            "earned_kopeks": int(rows[1] or 0),
        }

    async def top_referrers(self, limit: int = 10) -> list[tuple[int, int, int]]:
        """[(user_id, приглашённых с оплатой, заработано)] — для админской статистики."""
        stmt = (
            select(
                Referral.referrer_id,
                func.count(func.distinct(Referral.referee_id)),
                func.coalesce(func.sum(Referral.reward_kopeks), 0),
            )
            .where(Referral.paid.is_(True))
            .group_by(Referral.referrer_id)
            .order_by(func.coalesce(func.sum(Referral.reward_kopeks), 0).desc())
            .limit(limit)
        )
        return [
            (int(user_id), int(count), int(total))
            for user_id, count, total in (await self.session.execute(stmt)).all()
        ]


__all__ = ["ReferralRepository"]
