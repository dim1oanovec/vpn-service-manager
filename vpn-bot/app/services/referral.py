from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Payment, Referral, User
from app.utils.logging import get_logger

log = get_logger(__name__)


def parse_ref_payload(payload: str | None) -> int | None:
    """Поддерживаем /start ref123456 и /start 123456."""
    if not payload:
        return None
    cleaned = payload.strip()
    for prefix in ("ref", "r_", "ref_"):
        if cleaned.lower().startswith(prefix):
            cleaned = cleaned[len(prefix) :]
            break
    return int(cleaned) if cleaned.isdigit() else None


def ref_link(bot_username: str, telegram_id: int) -> str:
    return f"https://t.me/{bot_username}?start=ref{telegram_id}"


async def reward_for_payment(
    session: AsyncSession, payment: Payment
) -> tuple[User, int] | None:
    """Начисляет рефереру процент от оплаты на внутренний баланс."""
    if payment.amount_kopeks <= 0 or settings.referral_percent <= 0:
        return None

    buyer = await session.get(User, payment.user_id)
    if buyer is None or buyer.referrer_id is None:
        return None
    referrer = await session.get(User, buyer.referrer_id)
    if referrer is None:
        return None

    already = await session.scalar(
        select(Referral.id).where(Referral.payment_id == payment.id).limit(1)
    )
    if already:
        return None

    reward = payment.amount_kopeks * settings.referral_percent // 100
    if reward <= 0:
        return None

    referrer.balance_kopeks += reward

    existing = await session.scalar(
        select(Referral)
        .where(
            Referral.referrer_id == referrer.id,
            Referral.referee_id == buyer.id,
            Referral.payment_id.is_(None),
        )
        .limit(1)
    )
    if existing is not None:
        existing.payment_id = payment.id
        existing.reward_kopeks = reward
        existing.paid = True
    else:
        session.add(
            Referral(
                referrer_id=referrer.id,
                referee_id=buyer.id,
                payment_id=payment.id,
                reward_kopeks=reward,
                paid=True,
            )
        )
    await session.flush()
    log.info(
        "referral: %s получил %s коп. за оплату payment#%s",
        referrer.telegram_id,
        reward,
        payment.id,
    )
    return referrer, reward
