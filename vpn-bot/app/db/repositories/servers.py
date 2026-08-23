from __future__ import annotations

from sqlalchemy import func, select

from app.db.models import Server, Subscription, SubscriptionStatus
from app.db.repositories.base import BaseRepository, RepositoryError
from app.utils.time import utcnow


class NoServerAvailableError(RepositoryError):
    """Нет активного сервера со свободными слотами."""


class ServerRepository(BaseRepository[Server]):
    model = Server

    async def get_by_code(self, code: str) -> Server | None:
        stmt = select(Server).where(Server.code == code)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_active(self) -> list[Server]:
        return await self.list(
            Server.is_active.is_(True), order_by=(Server.sort_order, Server.id)
        )

    async def list_all(self) -> list[Server]:
        return await self.list(order_by=(Server.sort_order, Server.id))

    async def active_clients(self, server_id: int) -> int:
        """Число живых ключей на сервере — основа балансировки (§2.3 ТЗ)."""
        stmt = select(func.count()).select_from(Subscription).where(
            Subscription.server_id == server_id,
            Subscription.status.in_(
                (SubscriptionStatus.active, SubscriptionStatus.disabled)
            ),
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def load_counts(self) -> dict[int, int]:
        """{server_id: активных клиентов} одним запросом — для админки и выбора сервера."""
        stmt = (
            select(Subscription.server_id, func.count())
            .where(
                Subscription.status.in_(
                    (SubscriptionStatus.active, SubscriptionStatus.disabled)
                )
            )
            .group_by(Subscription.server_id)
        )
        rows = (await self.session.execute(stmt)).all()
        return {int(server_id): int(count) for server_id, count in rows}

    async def list_countries(self) -> list[Server]:
        """По одному представителю на страну — для меню выбора страны.

        Внутри страны берётся наименее загруженный сервер, поэтому пользователь
        видит страны, а балансировка остаётся скрытой.
        """
        servers = await self.list_active()
        counts = await self.load_counts()
        best: dict[str, Server] = {}
        for server in servers:
            if counts.get(server.id, 0) >= server.max_clients:
                continue
            current = best.get(server.country_name)
            if current is None or counts.get(server.id, 0) < counts.get(current.id, 0):
                best[server.country_name] = server
        return sorted(best.values(), key=lambda s: (s.sort_order, s.id))

    async def pick_for_country(self, country_name: str | None = None) -> Server:
        """Выбор сервера: активный, со свободными слотами, наименее загруженный."""
        servers = await self.list_active()
        counts = await self.load_counts()
        candidates = [
            server
            for server in servers
            if (country_name is None or server.country_name == country_name)
            and counts.get(server.id, 0) < server.max_clients
        ]
        if not candidates:
            raise NoServerAvailableError(
                f"нет свободного сервера для страны {country_name or 'любой'}"
            )
        candidates.sort(key=lambda s: (counts.get(s.id, 0), s.sort_order, s.id))
        return candidates[0]

    async def mark_checked(self, server: Server, error: str | None = None) -> None:
        server.last_checked_at = utcnow()
        server.last_error = error
        await self.session.flush()


__all__ = ["NoServerAvailableError", "ServerRepository"]
