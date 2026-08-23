from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Payment,
    PaymentProvider,
    PaymentStatus,
    ProvisionStatus,
)
from app.utils.time import utcnow


class PaymentsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def by_id(self, payment_id: int) -> Payment | None:
        return await self.session.get(Payment, payment_id)

    async def by_external_id(self, external_id: str) -> Payment | None:
        result = await self.session.execute(
            select(Payment).where(Payment.external_id == external_id)
        )
        return result.scalar_one_or_none()

    async def by_code(self, code: str) -> Payment | None:
        result = await self.session.execute(select(Payment).where(Payment.code == code))
        return result.scalar_one_or_none()

    async def create(self, **values: object) -> Payment:
        payment = Payment(**values)  # type: ignore[arg-type]
        self.session.add(payment)
        await self.session.flush()
        return payment

    async def of_user(self, user_id: int, limit: int = 10) -> list[Payment]:
        result = await self.session.execute(
            select(Payment)
            .where(Payment.user_id == user_id)
            .order_by(Payment.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars())

    async def cancel_other_pending(self, user_id: int, keep_id: int | None = None) -> int:
        """Один pending-платёж на пользователя: остальные автоотмена."""
        stmt = (
            update(Payment)
            .where(Payment.user_id == user_id, Payment.status == PaymentStatus.pending)
            .values(status=PaymentStatus.canceled)
        )
        if keep_id is not None:
            stmt = stmt.where(Payment.id != keep_id)
        result = await self.session.execute(stmt)
        return int(result.rowcount or 0)

    async def set_status(
        self,
        payment: Payment,
        status: PaymentStatus,
        *,
        external_id: str | None = None,
        admin_id: int | None = None,
    ) -> Payment:
        payment.status = status
        if external_id:
            payment.external_id = external_id
        if admin_id:
            payment.admin_id = admin_id
        if status == PaymentStatus.paid and payment.paid_at is None:
            payment.paid_at = utcnow()
        await self.session.flush()
        return payment

    async def pending_yookassa(self, older_than_seconds: int = 120) -> list[Payment]:
        threshold = utcnow() - timedelta(seconds=older_than_seconds)
        result = await self.session.execute(
            select(Payment).where(
                Payment.provider == PaymentProvider.yookassa,
                Payment.status == PaymentStatus.pending,
                Payment.external_id.is_not(None),
                Payment.created_at <= threshold,
            )
        )
        return list(result.scalars())

    async def pending_manual(self, limit: int = 20) -> list[Payment]:
        result = await self.session.execute(
            select(Payment)
            .where(
                Payment.provider == PaymentProvider.manual,
                Payment.status == PaymentStatus.pending,
                Payment.receipt_file_id.is_not(None),
            )
            .order_by(Payment.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars())

    async def failed_provisioning(self, limit: int = 20) -> list[Payment]:
        result = await self.session.execute(
            select(Payment)
            .where(
                Payment.status == PaymentStatus.paid,
                Payment.provision_status.in_(
                    [ProvisionStatus.failed, ProvisionStatus.pending]
                ),
                Payment.provision_attempts < 3,
                (Payment.provision_next_at.is_(None))
                | (Payment.provision_next_at <= utcnow()),
            )
            .order_by(Payment.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars())

    async def revenue_since(self, since: datetime) -> int:
        result = await self.session.execute(
            select(func.coalesce(func.sum(Payment.amount_kopeks), 0)).where(
                Payment.status == PaymentStatus.paid,
                Payment.paid_at >= since,
                Payment.provider != PaymentProvider.balance,
            )
        )
        return int(result.scalar_one())

    async def paid_count_of_user(self, user_id: int) -> int:
        result = await self.session.execute(
            select(func.count(Payment.id)).where(
                Payment.user_id == user_id, Payment.status == PaymentStatus.paid
            )
        )
        return int(result.scalar_one())

    async def all_paid(self) -> list[Payment]:
        result = await self.session.execute(
            select(Payment)
            .where(Payment.status == PaymentStatus.paid)
            .order_by(Payment.paid_at.desc())
        )
        return list(result.scalars())
