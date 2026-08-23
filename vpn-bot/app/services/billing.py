from __future__ import annotations

from dataclasses import dataclass

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import (
    Payment,
    PaymentProvider,
    PaymentStatus,
    Plan,
    Server,
    Subscription,
    User,
)
from app.db.repositories import audit as audit_repo
from app.db.repositories import payments as payments_repo
from app.db.repositories import servers as servers_repo
from app.db.session import lock_row
from app.services import promo as promo_service
from app.services import referral as referral_service
from app.services.payments.base import Quote
from app.services.provisioning import Connection, build_connection, grant_access
from app.utils.logging import get_logger
from app.utils.rate_limit import named_locks
from app.utils.time import money

log = get_logger(__name__)


@dataclass(slots=True)
class GrantResult:
    subscription: Subscription
    connection: Connection | None
    error: str | None = None


async def build_quote(
    session: AsyncSession, *, plan: Plan, user: User, promo_code: str | None = None
) -> tuple[Quote, str | None]:
    """Возвращает расчёт заказа и текст ошибки промокода (если был невалиден)."""
    quote = Quote(
        plan_id=plan.id,
        plan_title=plan.title,
        duration_days=plan.duration_days,
        device_limit=plan.device_limit,
        base_price_kopeks=plan.price_kopeks,
        price_kopeks=plan.price_kopeks,
        price_stars=plan.price_stars,
    )
    if not promo_code:
        return quote, None

    result = await promo_service.apply(session, code=promo_code, user=user, plan=plan)
    if not result.ok:
        return quote, result.error

    quote.price_kopeks = result.price_kopeks
    quote.bonus_days = result.bonus_days
    quote.promo_code = result.code
    if plan.price_kopeks > 0:
        quote.price_stars = max(
            1, round(plan.price_stars * result.price_kopeks / plan.price_kopeks)
        )
    return quote, None


async def resolve_server(
    session: AsyncSession, *, country_name: str | None
) -> Server | None:
    return await servers_repo.pick_for_country(session, country_name)


async def finalize_payment(
    session: AsyncSession,
    *,
    bot: Bot,
    payment: Payment,
    external_id: str | None = None,
) -> GrantResult:
    """Единая точка завершения оплаты: статус -> выдача -> рефералка.

    Идемпотентна: повторный вызов по уже оплаченному платежу вернёт ту же подписку.
    """
    async with named_locks.get(f"payment:{payment.id}"):
        await lock_row(session, "payments", payment.id)
        await session.refresh(payment)

        if payment.status is PaymentStatus.paid and payment.subscription_id:
            subscription = await session.get(Subscription, payment.subscription_id)
            if subscription is not None:
                server = await servers_repo.get(session, subscription.server_id)
                connection = (
                    await build_connection(server, subscription) if server else None
                )
                return GrantResult(subscription=subscription, connection=connection)

        if external_id and not payment.external_id:
            payment.external_id = external_id

        plan = payment.plan or (
            await session.get(Plan, payment.plan_id) if payment.plan_id else None
        )
        if plan is None:
            raise ValueError(f"payment#{payment.id}: тариф не найден")

        user = payment.user or await session.get(User, payment.user_id)
        if user is None:
            raise ValueError(f"payment#{payment.id}: пользователь не найден")

        server = (
            await servers_repo.get(session, payment.server_id)
            if payment.server_id
            else await servers_repo.pick_for_country(session, None)
        )
        if server is None:
            raise ValueError(f"payment#{payment.id}: нет доступного сервера")

        await payments_repo.set_status(session, payment, PaymentStatus.paid)
        days = plan.duration_days + (payment.bonus_days or 0)

        try:
            subscription = await grant_access(
                session,
                user=user,
                plan=plan,
                server=server,
                payment_id=payment.id,
                days=days,
            )
        except Exception as exc:  # noqa: BLE001 - падение панели не должно терять оплату
            log.exception("payment#%s: выдача доступа не удалась", payment.id)
            payment.provision_attempts += 1
            await payments_repo.set_status(session, payment, PaymentStatus.provision_failed)
            await notify_admins(
                bot,
                f"⚠️ Оплата прошла, выдача упала\n"
                f"payment#{payment.id} · user {user.telegram_id} · {plan.title}\n"
                f"Ошибка: {exc}",
            )
            raise

        await promo_service.commit_use(
            session, code=payment.promo_code, user=user, payment_id=payment.id
        )

        if payment.provider is not PaymentProvider.balance:
            reward = await referral_service.reward_for_payment(session, payment)
            if reward is not None:
                referrer, amount = reward
                await safe_send(
                    bot,
                    referrer.telegram_id,
                    f"💸 Реферальное начисление: {money(amount)}\n"
                    f"Ваш приглашённый оплатил подписку. Баланс: {money(referrer.balance_kopeks)}",
                )

        await audit_repo.write(
            session,
            actor_telegram_id=user.telegram_id,
            action="payment_completed",
            entity="payment",
            entity_id=payment.id,
            payload={
                "provider": payment.provider.value,
                "amount_kopeks": payment.amount_kopeks,
                "plan": plan.code,
                "server": server.code,
            },
        )

        connection = await build_connection(server, subscription)
        return GrantResult(subscription=subscription, connection=connection)


async def charge_balance(
    session: AsyncSession, *, user: User, amount_kopeks: int
) -> bool:
    if user.balance_kopeks < amount_kopeks:
        return False
    user.balance_kopeks -= amount_kopeks
    await session.flush()
    return True


async def safe_send(bot: Bot, chat_id: int, text: str, **kwargs: object) -> bool:
    """Отправка, которая не роняет вызывающий код на заблокировавших бота."""
    from aiogram.exceptions import TelegramAPIError

    try:
        await bot.send_message(chat_id, text, **kwargs)  # type: ignore[arg-type]
        return True
    except TelegramAPIError as exc:
        log.warning("send_message %s не доставлено: %s", chat_id, exc)
        return False


async def notify_admins(bot: Bot, text: str, **kwargs: object) -> None:
    targets: list[int] = []
    if settings.admin_chat_id:
        targets.append(settings.admin_chat_id)
    else:
        targets.extend(settings.admin_ids)
    for chat_id in targets:
        await safe_send(bot, chat_id, text, **kwargs)
