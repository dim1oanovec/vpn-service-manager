from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Server, Subscription, SubscriptionStatus


class ServersRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def by_id(self, server_id: int) -> Server | None:
        return await self.session.get(Server, server_id)

    async def by_code(self, code: str) -> Server | None:
        result = await self.session.execute(select(Server).where(Server.code == code))
        return result.scalar_one_or_none()

    async def all(self, only_active: bool = False) -> list[Server]:
        stmt = select(Server).order_by(Server.sort_order, Server.id)
        if only_active:
            stmt = stmt.where(Server.is_active.is_(True))
        result = await self.session.execute(stmt)
        return list(result.scalars())

    async def countries(self) -> list[tuple[str, str, str]]:
        """Уникальные страны активных серверов: (country_name, flag, любой code страны)."""
        servers = await self.all(only_active=True)
        seen: dict[str, tuple[str, str, str]] = {}
        for server in servers:
            if server.country_name not in seen:
                seen[server.country_name] = (
                    server.country_name,
                    server.country_flag,
                    server.code,
                )
        return list(seen.values())

    async def active_clients(self, server_id: int) -> int:
        result = await self.session.execute(
            select(func.count(Subscription.id)).where(
                Subscription.server_id == server_id,
                Subscription.status == SubscriptionStatus.active,
            )
        )
        return int(result.scalar_one())

    async def pick_for_country(self, country_name: str | None = None) -> Server | None:
        """Наименее загруженный активный сервер страны с запасом по max_clients."""
        load_subq = (
            select(
                Subscription.server_id.label("server_id"),
                func.count(Subscription.id).label("clients"),
            )
            .where(Subscription.status == SubscriptionStatus.active)
            .group_by(Subscription.server_id)
            .subquery()
        )
        clients = func.coalesce(load_subq.c.clients, 0)

        stmt = (
            select(Server, clients.label("load"))
            .outerjoin(load_subq, load_subq.c.server_id == Server.id)
            .where(Server.is_active.is_(True), clients < Server.max_clients)
            .order_by(clients.asc(), Server.sort_order.asc(), Server.id.asc())
            .limit(1)
        )
        if country_name:
            stmt = stmt.where(Server.country_name == country_name)

        result = await self.session.execute(stmt)
        row = result.first()
        return row[0] if row else None

    async def create(self, **kwargs: object) -> Server:
        server = Server(**kwargs)  # type: ignore[arg-type]
        self.session.add(server)
        await self.session.flush()
        return server

    async def set_active(self, server: Server, is_active: bool) -> None:
        server.is_active = is_active
        await self.session.flush()

    async def load_by_server(self) -> dict[int, int]:
        result = await self.session.execute(
            select(Subscription.server_id, func.count(Subscription.id))
            .where(Subscription.status == SubscriptionStatus.active)
            .group_by(Subscription.server_id)
        )
        return {int(server_id): int(count) for server_id, count in result.all()}
