from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Referral, User
from app.utils.time import utcnow


class UsersRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def by_id(self, user_id: int) -> User | None:
        return await self.session.get(User, user_id)

    async def by_telegram_id(self, telegram_id: int) -> User | None:
        result = await self.session.execute(select(User).where(User.telegram_id == telegram_id))
        return result.scalar_one_or_none()

    async def search(self, query: str, limit: int = 10) -> list[User]:
        query = query.strip().lstrip("@")
        stmt = select(User)
        if query.isdigit():
            stmt = stmt.where(
                or_(User.telegram_id == int(query), User.id == int(query))
            )
        else:
            stmt = stmt.where(User.username.ilike(f"%{query}%"))
        result = await self.session.execute(stmt.limit(limit))
        return list(result.scalars())

    async def get_or_create(
        self,
        telegram_id: int,
        username: str | None,
        first_name: str | None,
        language_code: str | None,
    ) -> tuple[User, bool]:
        user = await self.by_telegram_id(telegram_id)
        if user is not None:
            changed = False
            if user.username != username:
                user.username = username
                changed = True
            if user.first_name != first_name:
                user.first_name = first_name
                changed = True
            if not user.is_reachable:
                user.is_reachable = True
                changed = True
            user.last_seen_at = utcnow()
            if changed:
                await self.session.flush()
            return user, False

        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            language_code=(language_code or "ru")[:8],
            last_seen_at=utcnow(),
        )
        self.session.add(user)
        await self.session.flush()
        return user, True

    async def touch(self, user: User) -> None:
        user.last_seen_at = utcnow()

    async def set_referrer(self, user: User, referrer: User) -> bool:
        """Реферер ставится один раз и только если это не сам пользователь."""
        if user.referrer_id is not None or referrer.id == user.id:
            return False
        user.referrer_id = referrer.id
        self.session.add(Referral(referrer_id=referrer.id, referee_id=user.id, reward_kopeks=0))
        await self.session.flush()
        return True

    async def add_balance(self, user: User, delta_kopeks: int) -> int:
        await self.session.execute(
            update(User)
            .where(User.id == user.id)
            .values(balance_kopeks=User.balance_kopeks + delta_kopeks)
        )
        await self.session.refresh(user, ["balance_kopeks"])
        return user.balance_kopeks

    async def set_banned(self, user: User, banned: bool) -> None:
        user.is_banned = banned
        await self.session.flush()

    async def mark_unreachable(self, telegram_id: int) -> None:
        await self.session.execute(
            update(User).where(User.telegram_id == telegram_id).values(is_reachable=False)
        )

    async def reset_trial(self, user: User) -> None:
        user.trial_used = False
        await self.session.flush()

    async def count_all(self) -> int:
        result = await self.session.execute(select(func.count(User.id)))
        return int(result.scalar_one())

    async def count_since(self, hours: int) -> int:
        since = utcnow() - timedelta(hours=hours)
        result = await self.session.execute(
            select(func.count(User.id)).where(User.created_at >= since)
        )
        return int(result.scalar_one())

    async def referrals_of(self, user_id: int) -> list[Referral]:
        result = await self.session.execute(
            select(Referral)
            .where(Referral.referrer_id == user_id)
            .order_by(Referral.created_at.desc())
        )
        return list(result.scalars())

    async def referral_earned(self, user_id: int) -> int:
        result = await self.session.execute(
            select(func.coalesce(func.sum(Referral.reward_kopeks), 0)).where(
                Referral.referrer_id == user_id, Referral.paid.is_(True)
            )
        )
        return int(result.scalar_one())

    async def referral_count(self, user_id: int) -> int:
        result = await self.session.execute(
            select(func.count(Referral.id)).where(Referral.referrer_id == user_id)
        )
        return int(result.scalar_one())
