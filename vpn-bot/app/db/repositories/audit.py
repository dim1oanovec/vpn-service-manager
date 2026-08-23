from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog


class AuditRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def log(
        self,
        action: str,
        *,
        actor_telegram_id: int | None = None,
        entity: str | None = None,
        entity_id: str | int | None = None,
        payload: dict | None = None,
    ) -> AuditLog:
        record = AuditLog(
            actor_telegram_id=actor_telegram_id,
            action=action,
            entity=entity,
            entity_id=str(entity_id) if entity_id is not None else None,
            payload=payload,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def recent(self, limit: int = 20) -> list[AuditLog]:
        result = await self.session.execute(
            select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
        )
        return list(result.scalars())
