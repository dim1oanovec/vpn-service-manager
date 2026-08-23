from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.utils.time import utcnow


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


class ProvisionStatus(str, enum.Enum):
    none = "none"
    pending = "pending"
    failed = "failed"
    done = "done"


class PromoType(str, enum.Enum):
    percent = "percent"
    fixed = "fixed"
    days = "days"


def _enum(python_enum: type[enum.Enum], name: str) -> Enum:
    """Строковый enum: одинаково работает в SQLite и PostgreSQL, миграции проще."""
    return Enum(
        python_enum,
        name=name,
        native_enum=False,
        values_callable=lambda members: [item.value for item in members],
        length=32,
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(128))
    language_code: Mapped[str] = mapped_column(String(8), default="ru", nullable=False)
    referrer_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    balance_kopeks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    trial_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_reachable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    subscriptions: Mapped[list[Subscription]] = relationship(
        back_populates="user", lazy="noload"
    )

    @property
    def display_name(self) -> str:
        if self.username:
            return f"@{self.username}"
        return self.first_name or f"id{self.telegram_id}"


class Server(Base, TimestampMixin):
    __tablename__ = "servers"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    country_name: Mapped[str] = mapped_column(String(64), nullable=False)
    country_flag: Mapped[str] = mapped_column(String(8), default="", nullable=False)

    xui_base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    xui_username: Mapped[str] = mapped_column(String(128), nullable=False)
    xui_password: Mapped[str] = mapped_column(String(512), nullable=False)
    server_host: Mapped[str] = mapped_column(String(255), nullable=False)
    inbound_id: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    sub_url: Mapped[str | None] = mapped_column(String(512))
    protocol: Mapped[str] = mapped_column(String(32), default="vless-reality", nullable=False)

    max_clients: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False)

    subscriptions: Mapped[list[Subscription]] = relationship(
        back_populates="server", lazy="noload"
    )

    @property
    def title(self) -> str:
        return f"{self.country_flag} {self.country_name}".strip()


class Plan(Base, TimestampMixin):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(64), nullable=False)
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False)
    price_kopeks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    price_stars: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    device_limit: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    is_trial: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False)


class Subscription(Base, TimestampMixin):
    __tablename__ = "subscriptions"
    __table_args__ = (Index("ix_subscriptions_status_expires", "status", "expires_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    server_id: Mapped[int] = mapped_column(
        ForeignKey("servers.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("plans.id", ondelete="RESTRICT"), index=True, nullable=False
    )

    xui_client_uuid: Mapped[str] = mapped_column(String(64), nullable=False)
    xui_email: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    xui_sub_id: Mapped[str] = mapped_column(String(64), nullable=False)
    xui_inbound_id: Mapped[int] = mapped_column(Integer, nullable=False)

    status: Mapped[SubscriptionStatus] = mapped_column(
        _enum(SubscriptionStatus, "subscription_status"),
        default=SubscriptionStatus.active,
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    traffic_used_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reissued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    notified_3d: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notified_1d: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notified_3h: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notified_expired: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user: Mapped[User] = relationship(back_populates="subscriptions", lazy="joined")
    server: Mapped[Server] = relationship(back_populates="subscriptions", lazy="joined")
    plan: Mapped[Plan] = relationship(lazy="joined")


class Payment(Base, TimestampMixin):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("external_id", name="uq_payments_external_id"),
        Index("ix_payments_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False
    )
    subscription_id: Mapped[int | None] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="SET NULL")
    )
    server_id: Mapped[int | None] = mapped_column(ForeignKey("servers.id", ondelete="SET NULL"))

    provider: Mapped[PaymentProvider] = mapped_column(
        _enum(PaymentProvider, "payment_provider"), nullable=False
    )
    amount_kopeks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    amount_stars: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="RUB", nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(128))
    code: Mapped[str | None] = mapped_column(String(16), index=True)

    status: Mapped[PaymentStatus] = mapped_column(
        _enum(PaymentStatus, "payment_status"), default=PaymentStatus.pending, nullable=False
    )
    provision_status: Mapped[ProvisionStatus] = mapped_column(
        _enum(ProvisionStatus, "provision_status"), default=ProvisionStatus.none, nullable=False
    )
    provision_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    provision_next_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    promo_id: Mapped[int | None] = mapped_column(ForeignKey("promo_codes.id", ondelete="SET NULL"))
    discount_kopeks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bonus_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    renew_subscription_id: Mapped[int | None] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="SET NULL")
    )

    receipt_file_id: Mapped[str | None] = mapped_column(String(256))
    admin_id: Mapped[int | None] = mapped_column(BigInteger)
    payload: Mapped[dict | None] = mapped_column(JSON)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(lazy="joined")
    plan: Mapped[Plan] = relationship(lazy="joined")

    @property
    def is_renewal(self) -> bool:
        return self.renew_subscription_id is not None


class PromoCode(Base, TimestampMixin):
    __tablename__ = "promo_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    type: Mapped[PromoType] = mapped_column(_enum(PromoType, "promo_type"), nullable=False)
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    max_uses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    used_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class PromoUse(Base, TimestampMixin):
    __tablename__ = "promo_uses"
    __table_args__ = (UniqueConstraint("promo_id", "user_id", name="uq_promo_uses_promo_id_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    promo_id: Mapped[int] = mapped_column(
        ForeignKey("promo_codes.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    payment_id: Mapped[int | None] = mapped_column(ForeignKey("payments.id", ondelete="SET NULL"))


class Referral(Base, TimestampMixin):
    __tablename__ = "referrals"
    __table_args__ = (UniqueConstraint("payment_id", name="uq_referrals_payment_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    referrer_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    referee_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    payment_id: Mapped[int | None] = mapped_column(ForeignKey("payments.id", ondelete="SET NULL"))
    reward_kopeks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    paid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_telegram_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict | None] = mapped_column(JSON)


class SupportTicket(Base, TimestampMixin):
    __tablename__ = "support_tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    answered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text)
    admin_id: Mapped[int | None] = mapped_column(BigInteger)

    user: Mapped[User] = relationship(lazy="joined")
