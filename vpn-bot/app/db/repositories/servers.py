from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Server, Subscription, SubscriptionStatus


async def get(session: AsyncSession, server_id: int) -> Server | None:
    return await session.get(Server, server_id)


async def get_by_code(session: AsyncSession, code: str) -> Server | None:
    result = await session.execute(select(Server).where(Server.code == code))
    return result.scalar_one_or_none()


async def list_all(session: AsyncSession, only_active: bool = False) -> list[Server]:
    stmt = select(Server).order_by(Server.sort_order, Server.id)
    if only_active:
        stmt = stmt.where(Server.is_active.is_(True))
    result = await session.execute(stmt)
    return list(result.scalars())


async def list_countries(session: AsyncSession) -> list[str]:
    result = await session.execute(
        select(Server.country_name)
        .where(Server.is_active.is_(True))
        .group_by(Server.country_name)
        .order_by(func.min(Server.sort_order))
    )
    return list(result.scalars())


async def active_clients(session: AsyncSession, server_id: int) -> int:
    value = await session.scalar(
        select(func.count(Subscription.id)).where(
            Subscription.server_id == server_id,
            Subscription.status == SubscriptionStatus.active,
        )
    )
    return int(value or 0)


async def pick_for_country(session: AsyncSession, country_name: str | None = None) -> Server | None:
    """Балансировка: активный сервер страны с наименьшей загрузкой и запасом мест."""
    stmt = select(Server).where(Server.is_active.is_(True))
    if country_name:
        stmt = stmt.where(Server.country_name == country_name)
    result = await session.execute(stmt.order_by(Server.sort_order, Server.id))
    candidates = list(result.scalars())
    if not candidates:
        return None

    best: Server | None = None
    best_load = -1
    for server in candidates:
        load = await active_clients(session, server.id)
        if server.max_clients and load >= server.max_clients:
            continue
        if best is None or load < best_load:
            best, best_load = server, load
    return best
