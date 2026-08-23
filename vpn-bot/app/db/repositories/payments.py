from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.db.models import (
    Payment,
    PaymentProvider,
    PaymentStatus,
    ProvisionStatus,
)
from app.db.repositories.base import BaseRepository
from app.utils.time import utcnow

_LOCAL_CODE_ALPHABET = "ACDEFGHJKLMNPQRTUVWXY34789"  # без похожих символов (0/O, 1/I)


def generate_local_code() -> str:
    """Публичный код платежа — пользователь диктует его в комментарии к переводу."""
    return "P" + "".join(secrets.choice(_LOCAL_CODE_ALPHABET) for _ in range(7))


class PaymentRepository(BaseRepository[Payment]):
    model = Payment

    # ---------- создание ----------

    async def create_pending(
        self,
        *,
        user_id: int,
        plan_id: int,
        provider: PaymentProvider,
        amount_kopeks: int,
        discount_kopeks: int = 0,
        amount_stars: int = 0,
        currency: str = "RUB",
        server_id: int | None = None,
        promo_id: int | None = None,
        subscription_id: int | None = None,
        payload: dict | None = None,
    ) -> Payment:
        payment = Payment(
            user_id=user_id,
            plan_id=plan_id,
            provider=provider,
            status=PaymentStatus.pending,
            amount_kopeks=amount_kopeks,
            discount_kopeks=discount_kopeks,
            amount_stars=amount_stars,
            currency=currency,
            server_id=server_id,
            promo_id=promo_id,
            subscription_id=subscription_id,
            local_code=generate_local_code(),
            payload=payload,
        )
        self.session.add(payment)
        await self.session.flush()
        return payment

    # ---------- поиск ----------

    async def get_with_relations(self, payment_id: int) -> Payment | None:
        stmt = (
            select(Payment)
            .where(Payment.id == payment_id)
            .options(
                selectinload(Payment.user),
                selectinload(Payment.plan),
                selectinload(Payment.server),
                selectinload(Payment.subscription),
            )
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def get_by_external_id(self, external_id: str) -> Payment | None:
        """Ключ идемпотентности: payment.id ЮKassa или telegram_payment_charge_id."""
        stmt = select(Payment).where(Payment.external_id == external_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_local_code(self, local_code: str) -> Payment | None:
        stmt = select(Payment).where(Payment.local_code == local_code.strip().upper())
        return (await self.session.execute(stmt)).scalars().first()

    async def list_for_user(self, user_id: int, limit: int = 10) -> list[Payment]:
        stmt = (
            select(Payment)
            .where(Payment.user_id == user_id)
            .options(selectinload(Payment.plan))
            .order_by(Payment.id.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_pending_for_user(self, user_id: int) -> list[Payment]:
        return await self.list(
            Payment.user_id == user_id,
            Payment.status == PaymentStatus.pending,
            order_by=Payment.id.desc(),
        )

    async def cancel_other_pending(self, user_id: int, keep_payment_id: int | None = None) -> int:
        """Один pending-платёж на пользователя (§6.4 ТЗ) — остальные отменяем.

        Ручные платежи не трогаем: там пользователь уже мог отправить перевод и
        ждёт подтверждения администратора.
        """
        pending = await self.list(
            Payment.user_id == user_id,
            Payment.status == PaymentStatus.pending,
            Payment.provider != PaymentProvider.manual,
        )
        canceled = 0
        for payment in pending:
            if keep_payment_id is not None and payment.id == keep_payment_id:
                continue
            payment.status = PaymentStatus.canceled
            payment.failure_reason = "заменён новым платежом"
            canceled += 1
        if canceled:
            await self.session.flush()
        return canceled

    # ---------- очереди фоновых задач ----------

    async def list_stale_pending(
        self, provider: PaymentProvider, older_than: timedelta, limit: int = 100
    ) -> list[Payment]:
        """Страховка от потерянных вебхуков (`reconcile_payments`, §6.1 ТЗ)."""
        threshold = utcnow() - older_than
        stmt = (
            select(Payment)
            .where(
                Payment.provider == provider,
                Payment.status == PaymentStatus.pending,
                Payment.external_id.is_not(None),
                Payment.created_at <= threshold,
            )
            .order_by(Payment.created_at.asc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_provision_retry(self, limit: int = 50) -> list[Payment]:
        """Оплачено, но доступ не выдан (`retry_provisioning`, §7.4 ТЗ)."""
        now = utcnow()
        stmt = (
            select(Payment)
            .where(
                Payment.status == PaymentStatus.paid,
                Payment.provision_status.in_(
                    (ProvisionStatus.failed, ProvisionStatus.pending)
                ),
                Payment.provision_attempts < 3,
                Payment.provision_next_retry_at.is_not(None),
                Payment.provision_next_retry_at <= now,
            )
            .options(selectinload(Payment.user), selectinload(Payment.plan))
            .order_by(Payment.provision_next_retry_at.asc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    # ---------- переходы статусов ----------

    async def mark_paid(
        self,
        payment: Payment,
        *,
        external_id: str | None = None,
        admin_id: int | None = None,
    ) -> bool:
        """Возвращает False, если платёж уже был оплачен (повторный вебхук)."""
        if payment.status == PaymentStatus.paid:
            return False
        payment.status = PaymentStatus.paid
        payment.paid_at = utcnow()
        if external_id:
            payment.external_id = external_id
        if admin_id is not None:
            payment.admin_id = admin_id
        if payment.provision_status == ProvisionStatus.none:
            payment.provision_status = ProvisionStatus.pending
        await self.session.flush()
        return True

    async def mark_failed(
        self, payment: Payment, reason: str, status: PaymentStatus = PaymentStatus.failed
    ) -> None:
        payment.status = status
        payment.failure_reason = reason[:512]
        await self.session.flush()

    async def mark_provisioned(self, payment: Payment, subscription_id: int) -> None:
        payment.subscription_id = subscription_id
        payment.provision_status = ProvisionStatus.done
        payment.provision_error = None
        payment.provision_next_retry_at = None
        await self.session.flush()

    async def mark_provision_failed(self, payment: Payment, error: str) -> datetime | None:
        """Экспоненциальная задержка: 2, 8, 32 минуты. После 3 попыток — только вручную."""
        payment.provision_attempts += 1
        payment.provision_status = ProvisionStatus.failed
        payment.provision_error = error[:2000]
        if payment.provision_attempts >= 3:
            payment.provision_next_retry_at = None
        else:
            delay = timedelta(minutes=2 * (4 ** (payment.provision_attempts - 1)))
            payment.provision_next_retry_at = utcnow() + delay
        await self.session.flush()
        return payment.provision_next_retry_at

    async def attach_receipt(self, payment: Payment, file_id: str) -> None:
        payment.receipt_file_id = file_id
        await self.session.flush()

    # ---------- статистика (§9 ТЗ) ----------

    async def revenue_kopeks(self, since: datetime | None = None) -> int:
        stmt = select(
            func.coalesce(func.sum(Payment.amount_kopeks - Payment.discount_kopeks), 0)
        ).where(Payment.status == PaymentStatus.paid)
        if since is not None:
            stmt = stmt.where(Payment.paid_at >= since)
        return int((await self.session.execute(stmt)).scalar_one())

    async def count_paid(self, since: datetime | None = None) -> int:
        conditions = [Payment.status == PaymentStatus.paid]
        if since is not None:
            conditions.append(Payment.paid_at >= since)
        return await self.count(*conditions)

    async def revenue_by_plan(self, since: datetime | None = None) -> dict[int, int]:
        stmt = (
            select(
                Payment.plan_id,
                func.coalesce(
                    func.sum(Payment.amount_kopeks - Payment.discount_kopeks), 0
                ),
            )
            .where(Payment.status == PaymentStatus.paid)
            .group_by(Payment.plan_id)
        )
        if since is not None:
            stmt = stmt.where(Payment.paid_at >= since)
        return {
            int(plan_id): int(total)
            for plan_id, total in (await self.session.execute(stmt)).all()
        }

    async def list_pending_manual(self, limit: int = 20) -> list[Payment]:
        stmt = (
            select(Payment)
            .where(
                Payment.provider == PaymentProvider.manual,
                Payment.status == PaymentStatus.pending,
            )
            .options(selectinload(Payment.user), selectinload(Payment.plan))
            .order_by(Payment.created_at.asc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def has_any_paid(self, user_id: int) -> bool:
        return await self.exists(
            Payment.user_id == user_id, Payment.status == PaymentStatus.paid
        )


__all__ = ["PaymentRepository", "generate_local_code"]
