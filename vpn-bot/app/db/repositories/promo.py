from __future__ import annotations

from sqlalchemy import func, select

from app.db.models import PromoCode, PromoType, PromoUse
from app.db.repositories.base import BaseRepository
from app.utils.time import as_utc, utcnow


class PromoRepository(BaseRepository[PromoCode]):
    model = PromoCode

    @staticmethod
    def normalize(code: str) -> str:
        return code.strip().upper()

    async def get_by_code(self, code: str) -> PromoCode | None:
        stmt = select(PromoCode).where(
            func.upper(PromoCode.code) == self.normalize(code)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def list_all(self, only_active: bool = False) -> list[PromoCode]:
        conditions = [PromoCode.is_active.is_(True)] if only_active else []
        return await self.list(*conditions, order_by=PromoCode.id.desc())

    async def create_code(
        self,
        *,
        code: str,
        type: PromoType,
        value: int,
        max_uses: int = 0,
        per_user_limit: int = 1,
        expires_at=None,
        comment: str | None = None,
    ) -> PromoCode:
        promo = PromoCode(
            code=self.normalize(code),
            type=type,
            value=value,
            max_uses=max_uses,
            per_user_limit=per_user_limit,
            expires_at=expires_at,
            comment=comment,
        )
        self.session.add(promo)
        await self.session.flush()
        return promo

    def is_expired(self, promo: PromoCode) -> bool:
        return promo.expires_at is not None and as_utc(promo.expires_at) <= utcnow()

    def is_exhausted(self, promo: PromoCode) -> bool:
        return promo.max_uses > 0 and promo.used_count >= promo.max_uses

    async def uses_by_user(self, promo_id: int, user_id: int) -> int:
        stmt = (
            select(func.count())
            .select_from(PromoUse)
            .where(PromoUse.promo_id == promo_id, PromoUse.user_id == user_id)
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def register_use(
        self, promo: PromoCode, user_id: int, payment_id: int | None
    ) -> PromoUse:
        """Фиксация применения. Счётчик инкрементируется SQL-выражением —
        иначе два одновременных применения перезапишут друг друга."""
        use = PromoUse(promo_id=promo.id, user_id=user_id, payment_id=payment_id)
        self.session.add(use)
        promo.used_count = PromoCode.used_count + 1  # type: ignore[assignment]
        await self.session.flush()
        await self.session.refresh(promo, attribute_names=["used_count"])
        return use

    async def deactivate(self, promo: PromoCode) -> None:
        promo.is_active = False
        await self.session.flush()

    async def list_uses(self, promo_id: int, limit: int = 50) -> list[PromoUse]:
        stmt = (
            select(PromoUse)
            .where(PromoUse.promo_id == promo_id)
            .order_by(PromoUse.id.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())


__all__ = ["PromoRepository"]
