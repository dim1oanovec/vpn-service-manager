from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models import Ticket, TicketMessage, TicketStatus
from app.db.repositories.base import BaseRepository
from app.utils.time import utcnow


class TicketRepository(BaseRepository[Ticket]):
    model = Ticket

    async def get_with_messages(self, ticket_id: int) -> Ticket | None:
        stmt = (
            select(Ticket)
            .where(Ticket.id == ticket_id)
            .options(selectinload(Ticket.messages), selectinload(Ticket.user))
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def get_open_for_user(self, user_id: int) -> Ticket | None:
        """Незакрытое обращение переиспользуется — иначе на каждое сообщение
        в админ-чате появлялась бы новая карточка."""
        stmt = (
            select(Ticket)
            .where(
                Ticket.user_id == user_id,
                Ticket.status != TicketStatus.closed,
            )
            .order_by(Ticket.id.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def open_ticket(
        self, user_id: int, text: str | None, *, file_id: str | None = None
    ) -> tuple[Ticket, TicketMessage]:
        ticket = await self.get_open_for_user(user_id)
        if ticket is None:
            ticket = Ticket(
                user_id=user_id,
                status=TicketStatus.open,
                subject=(text or "")[:255] or None,
            )
            self.session.add(ticket)
            await self.session.flush()
        else:
            ticket.status = TicketStatus.open

        message = await self.add_message(
            ticket,
            text=text,
            file_id=file_id,
            is_from_admin=False,
            author_telegram_id=None,
        )
        return ticket, message

    async def add_message(
        self,
        ticket: Ticket,
        *,
        text: str | None,
        file_id: str | None = None,
        is_from_admin: bool = False,
        author_telegram_id: int | None = None,
    ) -> TicketMessage:
        message = TicketMessage(
            ticket_id=ticket.id,
            text=text,
            file_id=file_id,
            is_from_admin=is_from_admin,
            author_telegram_id=author_telegram_id,
        )
        self.session.add(message)
        if is_from_admin:
            ticket.status = TicketStatus.answered
        await self.session.flush()
        return message

    async def close(self, ticket: Ticket) -> None:
        ticket.status = TicketStatus.closed
        ticket.closed_at = utcnow()
        await self.session.flush()

    async def list_open(self, limit: int = 20) -> list[Ticket]:
        stmt = (
            select(Ticket)
            .where(Ticket.status != TicketStatus.closed)
            .options(selectinload(Ticket.user))
            .order_by(Ticket.created_at.asc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_open(self) -> int:
        return await self.count(Ticket.status != TicketStatus.closed)


__all__ = ["TicketRepository"]
