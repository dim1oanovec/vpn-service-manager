from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Referral, User
from app.utils.time import utcnow


async def get_by_telegram_id(session: AsyncSession, telegram_id: int) -> User | None:
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    return result.scalar_one_or_none()


async def get_by_id(session: AsyncSession, user_id: int) -> User | None:
    return await session.get(User, user_id)


async def find(session: AsyncSession, query: str) -> User | None:
    """Поиск по telegram_id или @username."""
    cleaned = query.strip().lstrip("@")
    if cleaned.isdigit():
        user = await get_by_telegram_id(session, int(cleaned))
        if user is not None:
            return user
    result = await session.execute(
        select(User).where(func.lower(User.username) == cleaned.lower())
    )
    return result.scalar_one_or_none()


async def get_or_create(
    session: AsyncSession,
    *,
    telegram_id: int,
    username: str | None,
    first_name: str | None,
    language_code: str | None,
    referrer_telegram_id: int | None = None,
) -> tuple[User, bool]:
    user = await get_by_telegram_id(session, telegram_id)
    if user is not None:
        user.username = username
        user.first_name = first_name
        user.last_seen_at = utcnow()
        if user.is_blocked_bot:
            user.is_blocked_bot = False
        await session.flush()
        return user, False

    referrer: User | None = None
    if referrer_telegram_id and referrer_telegram_id != telegram_id:
        referrer = await get_by_telegram_id(session, referrer_telegram_id)

    user = User(
        telegram_id=telegram_id,
        username=username,
        first_name=first_name,
        language_code=(language_code or "ru")[:8],
        referrer_id=referrer.id if referrer else None,
    )
    session.add(user)
    await session.flush()

    if referrer is not None:
        session.add(Referral(referrer_id=referrer.id, referee_id=user.id))
        await session.flush()
    return user, True


async def add_balance(session: AsyncSession, user: User, amount_kopeks: int) -> User:
    user.balance_kopeks = max(0, user.balance_kopeks + amount_kopeks)
    await session.flush()
    return user


async def referral_stats(session: AsyncSession, user: User) -> tuple[int, int]:
    """(кол-во приглашённых, суммарное вознаграждение в копейках)."""
    invited = await session.scalar(
        select(func.count(Referral.id)).where(Referral.referrer_id == user.id)
    )
    earned = await session.scalar(
        select(func.coalesce(func.sum(Referral.reward_kopeks), 0)).where(
            Referral.referrer_id == user.id
        )
    )
    return int(invited or 0), int(earned or 0)


async def list_for_broadcast(session: AsyncSession, segment: str) -> list[User]:
    from app.db.models import Payment, PaymentStatus, Subscription, SubscriptionStatus

    stmt = select(User).where(User.is_banned.is_(False), User.is_blocked_bot.is_(False))
    if segment == "active":
        stmt = stmt.where(
            User.id.in_(
                select(Subscription.user_id).where(
                    Subscription.status == SubscriptionStatus.active
                )
            )
        )
    elif segment == "expired":
        stmt = stmt.where(
            User.id.in_(
                select(Subscription.user_id).where(
                    Subscription.status.in_(
                        [SubscriptionStatus.expired, SubscriptionStatus.disabled]
                    )
                )
            ),
            User.id.notin_(
                select(Subscription.user_id).where(
                    Subscription.status == SubscriptionStatus.active
                )
            ),
        )
    elif segment == "trial":
        stmt = stmt.where(
            User.trial_used.is_(True),
            User.id.notin_(
                select(Payment.user_id).where(Payment.status == PaymentStatus.paid)
            ),
        )
    elif segment == "no_purchase":
        stmt = stmt.where(
            User.id.notin_(select(Payment.user_id).where(Payment.status == PaymentStatus.paid))
        )
    result = await session.execute(stmt.order_by(User.id))
    return list(result.scalars())
