from __future__ import annotations

import uuid as uuid_lib
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Plan, Server, Subscription, SubscriptionStatus, User
from app.db.repositories import servers as servers_repo
from app.services.xui import (
    XuiClient,
    XuiClientNotFound,
    build_subscription_url,
    build_vless_reality_link,
    connection_label,
    panel_pool,
)
from app.utils.crypto import new_sub_id, short_token
from app.utils.logging import get_logger
from app.utils.rate_limit import named_locks
from app.utils.time import extend_from, to_ms, utcnow

log = get_logger(__name__)


class ProvisioningError(Exception):
    """Не удалось создать/обновить клиента в панели."""


@dataclass(slots=True)
class Connection:
    """Готовые данные подключения для отправки пользователю."""

    vless_link: str
    subscription_url: str | None
    label: str

    @property
    def primary(self) -> str:
        return self.subscription_url or self.vless_link


def make_email(telegram_id: int) -> str:
    return f"tg{telegram_id}-{short_token(6)}"


async def pick_server(
    session: AsyncSession, country_name: str | None = None
) -> Server | None:
    return await servers_repo.pick_for_country(session, country_name)


async def _build_client(
    server: Server,
    *,
    uuid: str,
    email: str,
    sub_id: str,
    expires_at,
    device_limit: int,
    telegram_id: int,
    enable: bool = True,
) -> XuiClient:
    panel = await panel_pool.get(server)
    inbound = await panel.get_inbound(server.inbound_id)
    return XuiClient(
        id=uuid,
        email=email,
        flow=inbound.default_flow,
        limitIp=max(0, device_limit),
        totalGB=0,  # трафик безлимитный во всех тарифах
        expiryTime=to_ms(expires_at),
        enable=enable,
        tgId=str(telegram_id),
        subId=sub_id,
        comment=f"{settings.brand_name} bot",
        reset=0,
    )


async def build_connection(server: Server, subscription: Subscription) -> Connection:
    panel = await panel_pool.get(server)
    inbound = await panel.get_inbound(server.inbound_id)
    label = connection_label(settings.brand_name, server.country_flag, server.country_name)
    link = build_vless_reality_link(
        inbound=inbound,
        uuid=subscription.xui_client_uuid,
        host=server.server_host,
        label=label,
    )
    return Connection(
        vless_link=link,
        subscription_url=build_subscription_url(server.sub_url, subscription.xui_sub_id),
        label=label,
    )


async def create_subscription(
    session: AsyncSession,
    *,
    user: User,
    plan: Plan,
    server: Server,
    days: int | None = None,
) -> Subscription:
    """Создаёт нового клиента в панели и запись подписки."""
    duration = days if days is not None else plan.duration_days
    expires_at = extend_from(None, duration)
    uuid = str(uuid_lib.uuid4())
    email = make_email(user.telegram_id)
    sub_id = new_sub_id()

    client = await _build_client(
        server,
        uuid=uuid,
        email=email,
        sub_id=sub_id,
        expires_at=expires_at,
        device_limit=plan.device_limit,
        telegram_id=user.telegram_id,
    )
    panel = await panel_pool.get(server)
    await panel.add_client(server.inbound_id, client)

    subscription = Subscription(
        user_id=user.id,
        server_id=server.id,
        plan_id=plan.id,
        xui_client_uuid=uuid,
        xui_email=email,
        xui_sub_id=sub_id,
        xui_inbound_id=server.inbound_id,
        status=SubscriptionStatus.active,
        device_limit=plan.device_limit,
        started_at=utcnow(),
        expires_at=expires_at,
    )
    session.add(subscription)
    await session.flush()
    log.info(
        "subscription#%s создана: user=%s plan=%s server=%s",
        subscription.id,
        user.telegram_id,
        plan.code,
        server.code,
    )
    return subscription


async def extend_subscription(
    session: AsyncSession,
    subscription: Subscription,
    *,
    plan: Plan | None = None,
    days: int | None = None,
) -> Subscription:
    """Продление: ссылка и uuid сохраняются, в панели вызывается updateClient."""
    server = subscription.server or await servers_repo.get(session, subscription.server_id)
    if server is None:
        raise ProvisioningError("сервер подписки не найден")

    duration = days if days is not None else (plan.duration_days if plan else 0)
    if duration <= 0:
        raise ProvisioningError("некорректный срок продления")

    new_expiry = extend_from(subscription.expires_at, duration)
    device_limit = plan.device_limit if plan else subscription.device_limit

    client = await _build_client(
        server,
        uuid=subscription.xui_client_uuid,
        email=subscription.xui_email,
        sub_id=subscription.xui_sub_id or new_sub_id(),
        expires_at=new_expiry,
        device_limit=device_limit,
        telegram_id=subscription.user.telegram_id if subscription.user else 0,
    )
    panel = await panel_pool.get(server)
    try:
        await panel.update_client(subscription.xui_client_uuid, server.inbound_id, client)
    except XuiClientNotFound:
        # Админ удалил клиента вручную — пересоздаём с тем же uuid, фиксируем расхождение
        log.warning(
            "subscription#%s: клиента %s нет в панели, пересоздаю",
            subscription.id,
            subscription.xui_email,
        )
        await panel.add_client(server.inbound_id, client)

    subscription.expires_at = new_expiry
    subscription.status = SubscriptionStatus.active
    subscription.device_limit = device_limit
    if plan is not None:
        subscription.plan_id = plan.id
    subscription.notified_3d = False
    subscription.notified_1d = False
    subscription.notified_3h = False
    subscription.notified_expired = False
    await session.flush()
    log.info("subscription#%s продлена до %s", subscription.id, new_expiry.isoformat())
    return subscription


async def grant_access(
    session: AsyncSession,
    *,
    user: User,
    plan: Plan,
    server: Server,
    payment_id: int | None = None,
    days: int | None = None,
) -> Subscription:
    """Идемпотентная выдача доступа.

    Если для платежа подписка уже создана — возвращаем её.
    Если у пользователя есть подписка на этом сервере — продлеваем, иначе создаём.
    """
    lock_key = f"grant:{user.id}:{server.id}"
    async with named_locks.get(lock_key):
        if payment_id is not None:
            from app.db.repositories import payments as payments_repo

            payment = await payments_repo.get(session, payment_id)
            if payment is not None and payment.subscription_id:
                subscription = await session.get(Subscription, payment.subscription_id)
                if subscription is not None:
                    log.info(
                        "grant_access: payment#%s уже привязан к subscription#%s",
                        payment_id,
                        subscription.id,
                    )
                    return subscription

        from app.db.repositories import subscriptions as subs_repo

        current = await subs_repo.newest_active_for_server(session, user, server.id)
        duration = days if days is not None else plan.duration_days
        if current is not None:
            subscription = await extend_subscription(
                session, current, plan=plan, days=duration
            )
        else:
            subscription = await create_subscription(
                session, user=user, plan=plan, server=server, days=duration
            )

        if payment_id is not None:
            from app.db.repositories import payments as payments_repo

            payment = await payments_repo.get(session, payment_id)
            if payment is not None:
                payment.subscription_id = subscription.id
                payment.server_id = server.id
                await session.flush()
        return subscription


async def set_enabled(
    session: AsyncSession, subscription: Subscription, enabled: bool
) -> None:
    """Включение/отключение клиента в панели (для expire_check и админки)."""
    server = subscription.server or await servers_repo.get(session, subscription.server_id)
    if server is None:
        raise ProvisioningError("сервер подписки не найден")

    client = await _build_client(
        server,
        uuid=subscription.xui_client_uuid,
        email=subscription.xui_email,
        sub_id=subscription.xui_sub_id,
        expires_at=subscription.expires_at,
        device_limit=subscription.device_limit,
        telegram_id=subscription.user.telegram_id if subscription.user else 0,
        enable=enabled,
    )
    panel = await panel_pool.get(server)
    try:
        await panel.update_client(subscription.xui_client_uuid, server.inbound_id, client)
    except XuiClientNotFound:
        log.warning("subscription#%s: клиента нет в панели при set_enabled", subscription.id)
        return
    subscription.status = (
        SubscriptionStatus.active if enabled else SubscriptionStatus.disabled
    )
    await session.flush()


async def reissue(session: AsyncSession, subscription: Subscription) -> Connection:
    """Перевыпуск: новый uuid и subId, старая ссылка перестаёт работать."""
    server = subscription.server or await servers_repo.get(session, subscription.server_id)
    if server is None:
        raise ProvisioningError("сервер подписки не найден")

    new_uuid = str(uuid_lib.uuid4())
    new_sub = new_sub_id()
    client = await _build_client(
        server,
        uuid=new_uuid,
        email=subscription.xui_email,
        sub_id=new_sub,
        expires_at=subscription.expires_at,
        device_limit=subscription.device_limit,
        telegram_id=subscription.user.telegram_id if subscription.user else 0,
    )
    panel = await panel_pool.get(server)
    try:
        await panel.update_client(subscription.xui_client_uuid, server.inbound_id, client)
    except XuiClientNotFound:
        await panel.add_client(server.inbound_id, client)

    subscription.xui_client_uuid = new_uuid
    subscription.xui_sub_id = new_sub
    subscription.last_reissued_at = utcnow()
    await session.flush()
    log.info("subscription#%s перевыпущена", subscription.id)
    return await build_connection(server, subscription)


async def delete_from_panel(session: AsyncSession, subscription: Subscription) -> None:
    server = subscription.server or await servers_repo.get(session, subscription.server_id)
    if server is None:
        return
    panel = await panel_pool.get(server)
    try:
        await panel.delete_client(server.inbound_id, subscription.xui_client_uuid)
    except XuiClientNotFound:
        log.info("subscription#%s: клиент уже отсутствует в панели", subscription.id)
    subscription.status = SubscriptionStatus.deleted
    await session.flush()
