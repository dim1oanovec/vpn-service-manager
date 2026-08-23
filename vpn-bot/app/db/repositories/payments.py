from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Payment, PaymentProvider, PaymentStatus, Plan, User
from app.utils.crypto import payment_code
from app.utils.logging import get_logger
from app.utils.time import utcnow

log = get_logger(__name__)

OPEN_STATUSES = (PaymentStatus.pending, PaymentStatus.awaiting_review)


async def get(session: AsyncSession, payment_id: int) -> Payment | None:
    return await session.get(Payment, payment_id)


async def get_by_external_id(session: AsyncSession, external_id: str) -> Payment | None:
    result = await session.execute(select(Payment).where(Payment.external_id == external_id))
    return result.scalar_one_or_none()


async def get_by_code(session: AsyncSession, code: str) -> Payment | None:
    result = await session.execute(
        select(Payment).where(Payment.code == code).order_by(Payment.id.desc()).limit(1)
    )
    return result.scalar_one_or_none()


async def cancel_open_for_user(session: AsyncSession, user: User) -> int:
    """Один открытый платёж на пользователя: остальные автоотмена."""
    result = await session.execute(
        update(Payment)
        .where(Payment.user_id == user.id, Payment.status.in_(OPEN_STATUSES))
        .values(status=PaymentStatus.canceled)
    )
    return int(result.rowcount or 0)


async def create(
    session: AsyncSession,
    *,
    user: User,
    plan: Plan,
    provider: PaymentProvider,
    server_id: int | None,
    amount_kopeks: int,
    amount_stars: int = 0,
    currency: str = "RUB",
    promo_code: str | None = None,
    bonus_days: int = 0,
    status: PaymentStatus = PaymentStatus.pending,
    payload: dict | None = None,
) -> Payment:
    payment = Payment(
        user_id=user.id,
        plan_id=plan.id,
        server_id=server_id,
        provider=provider,
        amount_kopeks=amount_kopeks,
        amount_stars=amount_stars,
        currency=currency,
        promo_code=promo_code,
        bonus_days=bonus_days,
        status=status,
        code=payment_code(),
        payload=payload or {},
    )
    session.add(payment)
    await session.flush()
    log.info(
        "payment#%s создан: provider=%s status=%s amount=%s",
        payment.id,
        provider.value,
        status.value,
        amount_kopeks,
    )
    return payment


async def set_status(
    session: AsyncSession, payment: Payment, status: PaymentStatus, **extra: object
) -> Payment:
    previous = payment.status
    payment.status = status
    if status is PaymentStatus.paid and payment.paid_at is None:
        payment.paid_at = utcnow()
    for key, value in extra.items():
        setattr(payment, key, value)
    await session.flush()
    log.info("payment#%s: %s -> %s", payment.id, previous.value, status.value)
    return payment


async def list_pending_yookassa(session: AsyncSession, older_than_seconds: int = 120) -> list[Payment]:
    threshold = utcnow() - timedelta(seconds=older_than_seconds)
    result = await session.execute(
        select(Payment).where(
            Payment.provider == PaymentProvider.yookassa,
            Payment.status == PaymentStatus.pending,
            Payment.external_id.is_not(None),
            Payment.created_at <= threshold,
        )
    )
    return list(result.scalars())


async def list_awaiting_review(session: AsyncSession) -> list[Payment]:
    result = await session.execute(
        select(Payment)
        .where(Payment.status == PaymentStatus.awaiting_review)
        .order_by(Payment.id)
    )
    return list(result.scalars())


async def list_provision_failed(session: AsyncSession, max_attempts: int = 3) -> list[Payment]:
    result = await session.execute(
        select(Payment).where(
            Payment.status == PaymentStatus.provision_failed,
            Payment.provision_attempts < max_attempts,
        )
    )
    return list(result.scalars())


async def list_for_user(session: AsyncSession, user: User, limit: int = 10) -> list[Payment]:
    result = await session.execute(
        select(Payment)
        .where(Payment.user_id == user.id)
        .order_by(Payment.id.desc())
        .limit(limit)
    )
    return list(result.scalars())


async def list_all_paid(session: AsyncSession) -> list[Payment]:
    result = await session.execute(
        select(Payment).where(Payment.status == PaymentStatus.paid).order_by(Payment.id)
    )
    return list(result.scalars())
