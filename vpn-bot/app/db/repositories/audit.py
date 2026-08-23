from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import delete, select

from app.db.models import AuditLog, JobLock
from app.db.repositories.base import BaseRepository
from app.utils.time import as_utc, utcnow


class AuditRepository(BaseRepository[AuditLog]):
    model = AuditLog

    async def log(
        self,
        action: str,
        *,
        actor_telegram_id: int | None = None,
        entity: str | None = None,
        entity_id: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> AuditLog:
        """Запись административного/системного действия (§6.3, §9 ТЗ).

        В payload не должны попадать пароли панелей, ключи ЮKassa и полные
        vless-ссылки (§10 ТЗ) — вызывающий код передаёт только безопасные поля.
        """
        entry = AuditLog(
            action=action,
            actor_telegram_id=actor_telegram_id,
            entity=entity,
            entity_id=entity_id,
            payload=payload,
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def latest(self, limit: int = 20) -> list[AuditLog]:
        return await self.list(order_by=AuditLog.id.desc(), limit=limit)

    async def for_entity(self, entity: str, entity_id: int, limit: int = 20) -> list[AuditLog]:
        return await self.list(
            AuditLog.entity == entity,
            AuditLog.entity_id == entity_id,
            order_by=AuditLog.id.desc(),
            limit=limit,
        )

    async def purge_older_than(self, days: int) -> int:
        threshold = utcnow() - timedelta(days=days)
        result = await self.session.execute(
            delete(AuditLog).where(AuditLog.created_at < threshold)
        )
        return int(result.rowcount or 0)


class JobLockRepository(BaseRepository[JobLock]):
    """Кооперативный лок фоновых задач (§8 ТЗ).

    Задачи планировщика не должны выполняться параллельно (например, при двух
    запущенных инстансах бота). Лок берётся с TTL, чтобы упавший процесс не
    заблокировал задачу навсегда.
    """

    model = JobLock

    async def acquire(self, name: str, ttl_seconds: int, holder: str | None = None) -> bool:
        now = utcnow()
        lock = (
            await self.session.execute(select(JobLock).where(JobLock.name == name))
        ).scalar_one_or_none()

        if lock is None:
            self.session.add(
                JobLock(
                    name=name,
                    locked_until=now + timedelta(seconds=ttl_seconds),
                    holder=holder,
                )
            )
            await self.session.flush()
            return True

        if as_utc(lock.locked_until) > now:
            return False

        lock.locked_until = now + timedelta(seconds=ttl_seconds)
        lock.holder = holder
        await self.session.flush()
        return True

    async def release(self, name: str) -> None:
        lock = (
            await self.session.execute(select(JobLock).where(JobLock.name == name))
        ).scalar_one_or_none()
        if lock is not None:
            # Ставим срок в прошлое вместо удаления — строка переиспользуется.
            lock.locked_until = utcnow() - timedelta(seconds=1)
            await self.session.flush()


__all__ = ["AuditRepository", "JobLockRepository"]
