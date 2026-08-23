from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Plan, PromoCode, PromoType, User
from app.db.repositories import promo as promo_repo
from app.utils.time import as_utc, utcnow


@dataclass(slots=True)
class PromoResult:
    ok: bool
    error: str | None = None
    promo: PromoCode | None = None
    price_kopeks: int = 0
    bonus_days: int = 0
    discount_kopeks: int = 0

    @property
    def code(self) -> str | None:
        return self.promo.code if self.promo else None


async def apply(
    session: AsyncSession, *, code: str, user: User, plan: Plan
) -> PromoResult:
    """Считает итоговую цену на сервере. Клиентские данные не используются."""
    base_price = plan.price_kopeks
    promo = await promo_repo.get_by_code(session, code)
    if promo is None or not promo.is_active:
        return PromoResult(ok=False, error="Промокод не найден или отключён.", price_kopeks=base_price)
    if promo.expires_at is not None and as_utc(promo.expires_at) <= utcnow():
        return PromoResult(ok=False, error="Срок действия промокода истёк.", price_kopeks=base_price)
    if promo.max_uses and promo.used_count >= promo.max_uses:
        return PromoResult(ok=False, error="Лимит использований промокода исчерпан.", price_kopeks=base_price)
    if await promo_repo.used_by(session, promo, user):
        return PromoResult(ok=False, error="Вы уже использовали этот промокод.", price_kopeks=base_price)

    price = base_price
    bonus_days = 0
    if promo.type is PromoType.percent:
        price = max(0, base_price - base_price * min(promo.value, 100) // 100)
    elif promo.type is PromoType.fixed:
        price = max(0, base_price - promo.value * 100)
    elif promo.type is PromoType.days:
        bonus_days = promo.value

    return PromoResult(
        ok=True,
        promo=promo,
        price_kopeks=price,
        bonus_days=bonus_days,
        discount_kopeks=base_price - price,
    )


async def commit_use(
    session: AsyncSession, *, code: str | None, user: User, payment_id: int | None
) -> None:
    if not code:
        return
    promo = await promo_repo.get_by_code(session, code)
    if promo is None:
        return
    if await promo_repo.used_by(session, promo, user):
        return
    await promo_repo.register_use(session, promo, user, payment_id)


def describe(promo: PromoCode) -> str:
    if promo.type is PromoType.percent:
        return f"-{promo.value}%"
    if promo.type is PromoType.fixed:
        return f"-{promo.value} ₽"
    return f"+{promo.value} дн."
