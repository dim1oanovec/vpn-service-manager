"""Модели данных (§3 ТЗ).

Правила:
- все datetime — timezone-aware UTC в БД, конвертация в локальную зону только в UI;
- деньги — целые копейки (`*_kopeks`), никаких float;
- enum'ы хранятся строковыми значениями (`values_callable`), чтобы миграция была
  одинаковой на SQLite и PostgreSQL;
- уникальность объявляется ОДИН раз — именованным constraint'ом в `__table_args__`,
  не через `unique=True` на колонке (иначе получается дубль индексов).
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

# ---------------------------------------------------------------------------
# Перечисления
# ---------------------------------------------------------------------------


class SubscriptionStatus(str, enum.Enum):
    active = "active"
    expired = "expired"
    disabled = "disabled"
    deleted = "deleted"


class PaymentProvider(str, enum.Enum):
    yookassa = "yookassa"
    stars = "stars"
    manual = "manual"
    balance = "balance"


class PaymentStatus(str, enum.Enum):
    pending = "pending"
    paid = "paid"
    failed = "failed"
    refunded = "refunded"
    canceled = "canceled"


class PromoType(str, enum.Enum):
    percent = "percent"
    fixed = "fixed"
    days = "days"


class ProvisionStatus(str, enum.Enum):
    """Состояние выдачи доступа в панель (§7 ТЗ)."""

    none = "none"
    pending = "pending"
    done = "done"
    failed = "failed"


class TicketStatus(str, enum.Enum):
    open = "open"
    answered = "answered"
    closed = "closed"


def _enum(enum_cls: type[enum.Enum], name: str) -> SAEnum:
    """Строковый enum с явным именем типа — стабильно для Alembic и PostgreSQL."""
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        length=32,
        values_callable=lambda cls: [member.value for member in cls],
        validate_strings=True,
    )


def _dt(**kwargs: Any) -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), **kwargs)


# ---------------------------------------------------------------------------
# Пользователи
# ---------------------------------------------------------------------------


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("telegram_id", name="uq_users_telegram_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(128))
    language_code: Mapped[str | None] = mapped_column(String(8))

    referrer_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    balance_kopeks: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    trial_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_banned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_blocked_bot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ban_reason: Mapped[str | None] = mapped_column(String(255))
    last_seen_at: Mapped[datetime | None] = _dt()

    referrer: Mapped[User | None] = relationship(
        remote_side="User.id", back_populates="referrals_made", lazy="noload"
    )
    referrals_made: Mapped[list[User]] = relationship(
        back_populates="referrer", lazy="noload"
    )
    subscriptions: Mapped[list[Subscription]] = relationship(
        back_populates="user", lazy="noload", cascade="all, delete-orphan"
    )
    payments: Mapped[list[Payment]] = relationship(
        back_populates="user", lazy="noload", cascade="all, delete-orphan"
    )

    @property
    def display_name(self) -> str:
        if self.username:
            return f"@{self.username}"
        return self.first_name or str(self.telegram_id)

    def __repr__(self) -> str:  # pragma: no cover - отладочное представление
        return f"<User id={self.id} tg={self.telegram_id}>"


# ---------------------------------------------------------------------------
# Серверы и тарифы
# ---------------------------------------------------------------------------


class Server(TimestampMixin, Base):
    """Панель 3x-ui + параметры страны (§2.3 ТЗ)."""

    __tablename__ = "servers"
    __table_args__ = (UniqueConstraint("code", name="uq_servers_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    country_name: Mapped[str] = mapped_column(String(64), nullable=False)
    country_flag: Mapped[str] = mapped_column(String(16), nullable=False, default="")

    xui_base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    xui_username: Mapped[str] = mapped_column(String(128), nullable=False)
    # Хранится в виде "enc::<fernet>" — см. utils/crypto.py. В логи не попадает.
    xui_password: Mapped[str] = mapped_column(String(512), nullable=False)

    server_host: Mapped[str] = mapped_column(String(255), nullable=False)
    inbound_id: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sub_url: Mapped[str | None] = mapped_column(String(512))
    protocol: Mapped[str] = mapped_column(String(32), nullable=False, default="vless-reality")

    max_clients: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    last_error: Mapped[str | None] = mapped_column(Text)
    last_checked_at: Mapped[datetime | None] = _dt()

    subscriptions: Mapped[list[Subscription]] = relationship(
        back_populates="server", lazy="noload"
    )

    @property
    def title(self) -> str:
        return f"{self.country_flag} {self.country_name}".strip()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Server {self.code}>"


class Plan(TimestampMixin, Base):
    __tablename__ = "plans"
    __table_args__ = (UniqueConstraint("code", name="uq_plans_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False)
    price_kopeks: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    price_stars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    device_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    is_trial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    subscriptions: Mapped[list[Subscription]] = relationship(
        back_populates="plan", lazy="noload"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Plan {self.code}>"


# ---------------------------------------------------------------------------
# Подписки
# ---------------------------------------------------------------------------


class Subscription(TimestampMixin, Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint("xui_email", name="uq_subscriptions_xui_email"),
        Index("ix_subscriptions_user_id_status", "user_id", "status"),
        Index("ix_subscriptions_status_expires_at", "status", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    server_id: Mapped[int] = mapped_column(
        ForeignKey("servers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    xui_client_uuid: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    xui_email: Mapped[str] = mapped_column(String(128), nullable=False)
    xui_sub_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    xui_inbound_id: Mapped[int] = mapped_column(Integer, nullable=False)

    status: Mapped[SubscriptionStatus] = mapped_column(
        _enum(SubscriptionStatus, "subscription_status"),
        nullable=False,
        default=SubscriptionStatus.active,
    )
    device_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=3)

    started_at: Mapped[datetime] = _dt(nullable=False, server_default=func.now())
    expires_at: Mapped[datetime] = _dt(nullable=False)

    traffic_used_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    last_synced_at: Mapped[datetime | None] = _dt()
    last_reissued_at: Mapped[datetime | None] = _dt()

    notified_3d: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notified_1d: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notified_3h: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notified_expired: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    user: Mapped[User] = relationship(back_populates="subscriptions", lazy="noload")
    server: Mapped[Server] = relationship(back_populates="subscriptions", lazy="noload")
    plan: Mapped[Plan] = relationship(back_populates="subscriptions", lazy="noload")
    payments: Mapped[list[Payment]] = relationship(
        back_populates="subscription", lazy="noload"
    )

    def reset_notifications(self) -> None:
        """Вызывается при продлении — иначе напоминания не придут в новом цикле."""
        self.notified_3d = False
        self.notified_1d = False
        self.notified_3h = False
        self.notified_expired = False

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Subscription id={self.id} email={self.xui_email} status={self.status.value}>"


# ---------------------------------------------------------------------------
# Платежи
# ---------------------------------------------------------------------------


class Payment(TimestampMixin, Base):
    __tablename__ = "payments"
    __table_args__ = (
        # Основной механизм идемпотентности (§6.4 ТЗ). NULL-ы в UNIQUE допустимы
        # и в SQLite, и в PostgreSQL — до подтверждения external_id ещё нет.
        UniqueConstraint("external_id", name="uq_payments_external_id"),
        Index("ix_payments_user_id_status", "user_id", "status"),
        Index("ix_payments_status_created_at", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    subscription_id: Mapped[int | None] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="SET NULL"), index=True
    )
    server_id: Mapped[int | None] = mapped_column(
        ForeignKey("servers.id", ondelete="SET NULL")
    )
    promo_id: Mapped[int | None] = mapped_column(
        ForeignKey("promo_codes.id", ondelete="SET NULL")
    )

    provider: Mapped[PaymentProvider] = mapped_column(
        _enum(PaymentProvider, "payment_provider"), nullable=False
    )
    status: Mapped[PaymentStatus] = mapped_column(
        _enum(PaymentStatus, "payment_status"), nullable=False, default=PaymentStatus.pending
    )

    amount_kopeks: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    discount_kopeks: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    amount_stars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="RUB")

    # Провайдерский идентификатор: payment.id ЮKassa либо telegram_payment_charge_id.
    external_id: Mapped[str | None] = mapped_column(String(128))
    # Наш публичный код платежа — показывается пользователю при ручной оплате.
    local_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    confirmation_url: Mapped[str | None] = mapped_column(String(1024))
    receipt_file_id: Mapped[str | None] = mapped_column(String(256))

    provision_status: Mapped[ProvisionStatus] = mapped_column(
        _enum(ProvisionStatus, "provision_status"),
        nullable=False,
        default=ProvisionStatus.none,
    )
    provision_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provision_next_retry_at: Mapped[datetime | None] = _dt()
    provision_error: Mapped[str | None] = mapped_column(Text)

    admin_id: Mapped[int | None] = mapped_column(BigInteger)
    failure_reason: Mapped[str | None] = mapped_column(String(512))
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    paid_at: Mapped[datetime | None] = _dt()

    user: Mapped[User] = relationship(back_populates="payments", lazy="noload")
    plan: Mapped[Plan] = relationship(lazy="noload")
    subscription: Mapped[Subscription | None] = relationship(
        back_populates="payments", lazy="noload"
    )
    server: Mapped[Server | None] = relationship(lazy="noload")

    @property
    def total_kopeks(self) -> int:
        """Итог к оплате после скидки — источник истины для суммы у провайдера."""
        return max(self.amount_kopeks - self.discount_kopeks, 0)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Payment id={self.id} {self.provider.value} {self.status.value}>"


# ---------------------------------------------------------------------------
# Промокоды
# ---------------------------------------------------------------------------


class PromoCode(TimestampMixin, Base):
    __tablename__ = "promo_codes"
    __table_args__ = (UniqueConstraint("code", name="uq_promo_codes_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    type: Mapped[PromoType] = mapped_column(_enum(PromoType, "promo_type"), nullable=False)
    # percent -> проценты, fixed -> копейки, days -> дни.
    value: Mapped[int] = mapped_column(BigInteger, nullable=False)
    max_uses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 0 = без лимита
    used_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    per_user_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    expires_at: Mapped[datetime | None] = _dt()
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    comment: Mapped[str | None] = mapped_column(String(255))

    uses: Mapped[list[PromoUse]] = relationship(
        back_populates="promo", lazy="noload", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PromoCode {self.code} {self.type.value}={self.value}>"


class PromoUse(TimestampMixin, Base):
    __tablename__ = "promo_uses"
    __table_args__ = (Index("ix_promo_uses_promo_id_user_id", "promo_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    promo_id: Mapped[int] = mapped_column(
        ForeignKey("promo_codes.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("payments.id", ondelete="SET NULL")
    )

    promo: Mapped[PromoCode] = relationship(back_populates="uses", lazy="noload")
    user: Mapped[User] = relationship(lazy="noload")
    payment: Mapped[Payment | None] = relationship(lazy="noload")


# ---------------------------------------------------------------------------
# Рефералы
# ---------------------------------------------------------------------------


class Referral(TimestampMixin, Base):
    __tablename__ = "referrals"
    __table_args__ = (
        # Вознаграждение начисляется один раз за платёж приглашённого.
        UniqueConstraint("payment_id", name="uq_referrals_payment_id"),
        Index("ix_referrals_referrer_id_paid", "referrer_id", "paid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    referrer_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    referee_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("payments.id", ondelete="SET NULL")
    )
    reward_kopeks: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    paid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    referrer: Mapped[User] = relationship(foreign_keys=[referrer_id], lazy="noload")
    referee: Mapped[User] = relationship(foreign_keys=[referee_id], lazy="noload")


# ---------------------------------------------------------------------------
# Поддержка
# ---------------------------------------------------------------------------


class Ticket(TimestampMixin, Base):
    """Обращение в поддержку (§5.7 ТЗ). Переписка — в `ticket_messages`."""

    __tablename__ = "tickets"
    __table_args__ = (Index("ix_tickets_status_created_at", "status", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[TicketStatus] = mapped_column(
        _enum(TicketStatus, "ticket_status"), nullable=False, default=TicketStatus.open
    )
    subject: Mapped[str | None] = mapped_column(String(255))
    # message_id карточки в админ-чате — чтобы обновлять её при ответе.
    admin_message_id: Mapped[int | None] = mapped_column(BigInteger)
    closed_at: Mapped[datetime | None] = _dt()

    user: Mapped[User] = relationship(lazy="noload")
    messages: Mapped[list[TicketMessage]] = relationship(
        back_populates="ticket",
        lazy="noload",
        cascade="all, delete-orphan",
        order_by="TicketMessage.id",
    )


class TicketMessage(TimestampMixin, Base):
    __tablename__ = "ticket_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    is_from_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    author_telegram_id: Mapped[int | None] = mapped_column(BigInteger)
    text: Mapped[str | None] = mapped_column(Text)
    file_id: Mapped[str | None] = mapped_column(String(256))

    ticket: Mapped[Ticket] = relationship(back_populates="messages", lazy="noload")


# ---------------------------------------------------------------------------
# Аудит и служебное
# ---------------------------------------------------------------------------


class AuditLog(TimestampMixin, Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_entity_entity_id", "entity", "entity_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_telegram_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[int | None] = mapped_column(BigInteger)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class JobLock(Base):
    """Лок фоновых задач (§8 ТЗ) — одна задача не запускается дважды параллельно."""

    __tablename__ = "job_locks"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    locked_until: Mapped[datetime] = _dt(nullable=False)
    holder: Mapped[str | None] = mapped_column(String(64))


__all__ = [
    "AuditLog",
    "JobLock",
    "Payment",
    "PaymentProvider",
    "PaymentStatus",
    "Plan",
    "PromoCode",
    "PromoType",
    "PromoUse",
    "ProvisionStatus",
    "Referral",
    "Server",
    "Subscription",
    "SubscriptionStatus",
    "Ticket",
    "TicketMessage",
    "TicketStatus",
    "User",
]
