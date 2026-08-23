from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Plan


async def get(session: AsyncSession, plan_id: int) -> Plan | None:
    return await session.get(Plan, plan_id)


async def get_by_code(session: AsyncSession, code: str) -> Plan | None:
    result = await session.execute(select(Plan).where(Plan.code == code))
    return result.scalar_one_or_none()


async def list_paid(session: AsyncSession, only_active: bool = True) -> list[Plan]:
    stmt = select(Plan).where(Plan.is_trial.is_(False)).order_by(Plan.sort_order, Plan.id)
    if only_active:
        stmt = stmt.where(Plan.is_active.is_(True))
    result = await session.execute(stmt)
    return list(result.scalars())


async def list_all(session: AsyncSession) -> list[Plan]:
    result = await session.execute(select(Plan).order_by(Plan.sort_order, Plan.id))
    return list(result.scalars())


async def trial_plan(session: AsyncSession) -> Plan | None:
    result = await session.execute(
        select(Plan).where(Plan.is_trial.is_(True), Plan.is_active.is_(True)).limit(1)
    )
    return result.scalar_one_or_none()
