from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Plan


class PlansRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def by_id(self, plan_id: int) -> Plan | None:
        return await self.session.get(Plan, plan_id)

    async def by_code(self, code: str) -> Plan | None:
        result = await self.session.execute(select(Plan).where(Plan.code == code))
        return result.scalar_one_or_none()

    async def paid(self, only_active: bool = True) -> list[Plan]:
        stmt = select(Plan).where(Plan.is_trial.is_(False)).order_by(Plan.sort_order, Plan.id)
        if only_active:
            stmt = stmt.where(Plan.is_active.is_(True))
        result = await self.session.execute(stmt)
        return list(result.scalars())

    async def all(self) -> list[Plan]:
        result = await self.session.execute(select(Plan).order_by(Plan.sort_order, Plan.id))
        return list(result.scalars())

    async def trial(self) -> Plan | None:
        result = await self.session.execute(
            select(Plan).where(Plan.is_trial.is_(True), Plan.is_active.is_(True)).limit(1)
        )
        return result.scalar_one_or_none()

    async def upsert(self, code: str, **values: object) -> Plan:
        plan = await self.by_code(code)
        if plan is None:
            plan = Plan(code=code, **values)  # type: ignore[arg-type]
            self.session.add(plan)
        else:
            for key, value in values.items():
                setattr(plan, key, value)
        await self.session.flush()
        return plan
