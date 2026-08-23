from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SupportTicket


class SupportRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def by_id(self, ticket_id: int) -> SupportTicket | None:
        return await self.session.get(SupportTicket, ticket_id)

    async def create(self, user_id: int, message: str) -> SupportTicket:
        ticket = SupportTicket(user_id=user_id, message=message)
        self.session.add(ticket)
        await self.session.flush()
        return ticket

    async def answer(self, ticket: SupportTicket, answer: str, admin_id: int) -> SupportTicket:
        ticket.answer = answer
        ticket.answered = True
        ticket.admin_id = admin_id
        await self.session.flush()
        return ticket
