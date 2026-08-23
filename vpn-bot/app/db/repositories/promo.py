from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PromoCode, PromoUse, User


async def get_by_code(session: AsyncSession, code: str) -> PromoCode | None:
    result = await session.execute(
        select(PromoCode).where(func.upper(PromoCode.code) == code.strip().upper())
    )
    return result.scalar_one_or_none()


async def list_all(session: AsyncSession) -> list[PromoCode]:
    result = await session.execute(select(PromoCode).order_by(PromoCode.id.desc()))
    return list(result.scalars())


async def create(
    session: AsyncSession,
    *,
    code: str,
    promo_type: str,
    value: int,
    max_uses: int,
    expires_at: object | None = None,
) -> PromoCode:
    from app.db.models import PromoType

    promo = PromoCode(
        code=code.strip().upper(),
        type=PromoType(promo_type),
        value=value,
        max_uses=max_uses,
        expires_at=expires_at,  # type: ignore[arg-type]
    )
    session.add(promo)
    await session.flush()
    return promo


async def used_by(session: AsyncSession, promo: PromoCode, user: User) -> bool:
    result = await session.execute(
        select(PromoUse.id).where(PromoUse.promo_id == promo.id, PromoUse.user_id == user.id)
    )
    return result.scalar_one_or_none() is not None


async def register_use(
    session: AsyncSession, promo: PromoCode, user: User, payment_id: int | None
) -> None:
    session.add(PromoUse(promo_id=promo.id, user_id=user.id, payment_id=payment_id))
    promo.used_count += 1
    await session.flush()
