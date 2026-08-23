from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PromoCode, PromoType, PromoUse


class PromoRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def by_id(self, promo_id: int) -> PromoCode | None:
        return await self.session.get(PromoCode, promo_id)

    async def by_code(self, code: str) -> PromoCode | None:
        result = await self.session.execute(
            select(PromoCode).where(PromoCode.code == code.strip().upper())
        )
        return result.scalar_one_or_none()

    async def all(self, limit: int = 50) -> list[PromoCode]:
        result = await self.session.execute(
            select(PromoCode).order_by(PromoCode.created_at.desc()).limit(limit)
        )
        return list(result.scalars())

    async def create(
        self,
        *,
        code: str,
        promo_type: PromoType,
        value: int,
        max_uses: int = 0,
        expires_at: datetime | None = None,
    ) -> PromoCode:
        promo = PromoCode(
            code=code.strip().upper(),
            type=promo_type,
            value=value,
            max_uses=max_uses,
            expires_at=expires_at,
        )
        self.session.add(promo)
        await self.session.flush()
        return promo

    async def deactivate(self, promo: PromoCode) -> None:
        promo.is_active = False
        await self.session.flush()

    async def used_by(self, promo_id: int, user_id: int) -> bool:
        result = await self.session.execute(
            select(PromoUse.id).where(
                PromoUse.promo_id == promo_id, PromoUse.user_id == user_id
            )
        )
        return result.scalar_one_or_none() is not None

    async def register_use(
        self, promo: PromoCode, user_id: int, payment_id: int | None
    ) -> PromoUse:
        use = PromoUse(promo_id=promo.id, user_id=user_id, payment_id=payment_id)
        self.session.add(use)
        await self.session.execute(
            update(PromoCode)
            .where(PromoCode.id == promo.id)
            .values(used_count=PromoCode.used_count + 1)
        )
        await self.session.flush()
        return use
