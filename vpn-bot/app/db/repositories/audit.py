from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog
from app.utils.logging import get_logger

log = get_logger(__name__)


async def write(
    session: AsyncSession,
    *,
    actor_telegram_id: int | None,
    action: str,
    entity: str | None = None,
    entity_id: str | int | None = None,
    payload: dict | None = None,
) -> None:
    session.add(
        AuditLog(
            actor_telegram_id=actor_telegram_id,
            action=action,
            entity=entity,
            entity_id=str(entity_id) if entity_id is not None else None,
            payload=payload or {},
        )
    )
    await session.flush()
    log.info("audit: %s %s#%s by %s", action, entity, entity_id, actor_telegram_id)


async def last(session: AsyncSession, limit: int = 20) -> list[AuditLog]:
    result = await session.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit))
    return list(result.scalars())
