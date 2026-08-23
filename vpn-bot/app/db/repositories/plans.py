from __future__ import annotations

from sqlalchemy import select

from app.db.models import Plan
from app.db.repositories.base import BaseRepository


class PlanRepository(BaseRepository[Plan]):
    model = Plan

    async def get_by_code(self, code: str) -> Plan | None:
        stmt = select(Plan).where(Plan.code == code)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_purchasable(self) -> list[Plan]:
        """Платные активные тарифы для экрана покупки — триал сюда не попадает."""
        return await self.list(
            Plan.is_active.is_(True),
            Plan.is_trial.is_(False),
            order_by=(Plan.sort_order, Plan.duration_days),
        )

    async def list_all(self) -> list[Plan]:
        return await self.list(order_by=(Plan.sort_order, Plan.duration_days))

    async def get_trial(self) -> Plan | None:
        stmt = (
            select(Plan)
            .where(Plan.is_trial.is_(True), Plan.is_active.is_(True))
            .order_by(Plan.sort_order)
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()


__all__ = ["PlanRepository"]
