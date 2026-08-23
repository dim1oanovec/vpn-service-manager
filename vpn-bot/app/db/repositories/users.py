from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, or_, select, update

from app.db.models import Payment, PaymentStatus, Referral, Subscription, SubscriptionStatus, User
from app.db.repositories.base import BaseRepository, InsufficientBalanceError
from app.utils.time import utcnow


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        stmt = select(User).where(User.telegram_id == telegram_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_or_create(
        self,
        telegram_id: int,
        *,
        username: str | None = None,
        first_name: str | None = None,
        language_code: str | None = None,
    ) -> tuple[User, bool]:
        """Возвращает (пользователь, создан_ли). Профильные поля освежаются при каждом входе."""
        user = await self.get_by_telegram_id(telegram_id)
        if user is not None:
            changed = False
            if username != user.username:
                user.username = username
                changed = True
            if first_name and first_name != user.first_name:
                user.first_name = first_name
                changed = True
            if language_code and language_code != user.language_code:
                user.language_code = language_code
                changed = True
            if user.is_blocked_bot:
                # Пользователь вернулся — снимаем метку "заблокировал бота".
                user.is_blocked_bot = False
                changed = True
            user.last_seen_at = utcnow()
            if changed:
                await self.session.flush()
            return user, False

        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            language_code=language_code,
            last_seen_at=utcnow(),
        )
        self.session.add(user)
        await self.session.flush()
        return user, True

    async def search(self, query: str, limit: int = 20) -> list[User]:
        """Поиск для админки по telegram_id или username (§9 ТЗ)."""
        query = query.strip().lstrip("@")
        if not query:
            return []
        conditions = [User.username.ilike(f"%{query}%")]
        if query.isdigit():
            conditions.append(User.telegram_id == int(query))
        stmt = select(User).where(or_(*conditions)).order_by(User.id.desc()).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    async def set_referrer(self, user: User, referrer: User) -> bool:
        """Реферер фиксируется однократно и не может быть самим пользователем."""
        if user.referrer_id is not None or referrer.id == user.id:
            return False
        user.referrer_id = referrer.id
        await self.session.flush()
        return True

    async def change_balance(self, user: User, delta_kopeks: int) -> int:
        """Атомарное изменение баланса. Возвращает новый баланс.

        Инкремент считается SQL-выражением, а не `user.balance += x` в Python, чтобы не
        потерять параллельное начисление (например, реферальное во время покупки).
        При списании в WHERE добавляется проверка достатка средств — если денег не
        хватило, строка не обновится и мы поднимаем ошибку вместо ухода в минус.
        """
        if delta_kopeks == 0:
            return user.balance_kopeks

        stmt = (
            update(User)
            .where(User.id == user.id)
            .values(balance_kopeks=User.balance_kopeks + delta_kopeks)
        )
        if delta_kopeks < 0:
            stmt = stmt.where(User.balance_kopeks >= -delta_kopeks)

        result = await self.session.execute(stmt)
        if delta_kopeks < 0 and not result.rowcount:
            raise InsufficientBalanceError(
                f"недостаточно средств: нужно {-delta_kopeks}, доступно {user.balance_kopeks}"
            )

        await self.session.refresh(user, attribute_names=["balance_kopeks"])
        return user.balance_kopeks

    async def mark_trial_used(self, user: User) -> None:
        user.trial_used = True
        await self.session.flush()

    async def set_banned(self, user: User, banned: bool, reason: str | None = None) -> None:
        user.is_banned = banned
        user.ban_reason = reason if banned else None
        await self.session.flush()

    async def mark_blocked_bot(self, telegram_id: int) -> None:
        """Вызывается при TelegramForbiddenError в рассылке (§9 ТЗ)."""
        await self.session.execute(
            update(User).where(User.telegram_id == telegram_id).values(is_blocked_bot=True)
        )

    async def touch(self, user: User) -> None:
        user.last_seen_at = utcnow()

    # ---------- статистика ----------

    async def count_registered_since(self, since: datetime) -> int:
        return await self.count(User.created_at >= since)

    async def count_referrals(self, user_id: int) -> int:
        return int(
            (
                await self.session.execute(
                    select(func.count()).select_from(User).where(User.referrer_id == user_id)
                )
            ).scalar_one()
        )

    async def referral_earned_kopeks(self, user_id: int) -> int:
        stmt = select(func.coalesce(func.sum(Referral.reward_kopeks), 0)).where(
            Referral.referrer_id == user_id, Referral.paid.is_(True)
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def segment_telegram_ids(self, segment: str) -> list[int]:
        """Сегменты рассылки (§9 ТЗ): all | active | expired | trial | no_purchase."""
        base = select(User.telegram_id).where(
            User.is_banned.is_(False), User.is_blocked_bot.is_(False)
        )

        if segment == "active":
            sub = (
                select(Subscription.user_id)
                .where(
                    Subscription.status == SubscriptionStatus.active,
                    Subscription.expires_at > utcnow(),
                )
                .scalar_subquery()
            )
            base = base.where(User.id.in_(sub))
        elif segment == "expired":
            active = (
                select(Subscription.user_id)
                .where(
                    Subscription.status == SubscriptionStatus.active,
                    Subscription.expires_at > utcnow(),
                )
                .scalar_subquery()
            )
            ever = select(Subscription.user_id).scalar_subquery()
            base = base.where(User.id.in_(ever), User.id.not_in(active))
        elif segment == "trial":
            base = base.where(User.trial_used.is_(True))
        elif segment == "no_purchase":
            paid = (
                select(Payment.user_id)
                .where(Payment.status == PaymentStatus.paid)
                .scalar_subquery()
            )
            base = base.where(User.id.not_in(paid))
        elif segment != "all":
            raise ValueError(f"unknown segment: {segment}")

        return list((await self.session.execute(base)).scalars().all())

    async def is_account_old_enough(self, user: User, min_days: int) -> bool:
        """Антифрод для триала (§4 ТЗ): аккаунт в боте должен существовать N дней.

        Возраст самого Telegram-аккаунта точно узнать нельзя, поэтому берём дату
        первого визита в бота — этого достаточно против массовой регистрации.
        """
        if min_days <= 0:
            return True
        created = user.created_at
        if created is None:
            return False
        if created.tzinfo is None:
            created = created.replace(tzinfo=utcnow().tzinfo)
        return utcnow() - created >= timedelta(days=min_days)


__all__ = ["UserRepository"]
