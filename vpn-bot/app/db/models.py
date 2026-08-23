from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Enum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UtcDateTime
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
    trial = "trial"
    admin = "admin"


class PaymentStatus(str, enum.Enum):
    pending = "pending"
    awaiting_review = "awaiting_review"
    paid = "paid"
    provision_failed = "provision_failed"
    failed = "failed"
    refunded = "refunded"
    canceled = "canceled"


class PromoType(str, enum.Enum):
    percent = "percent"
    fixed = "fixed"
    days = "days"


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(128))
    language_code: Mapped[str] = mapped_column(String(8), default="ru")
    referrer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    balance_kopeks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    trial_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_blocked_bot: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, nullable=False)

    referrer: Mapped[User | None] = relationship(remote_side=[id], lazy="selectin")
    subscriptions: Mapped[list[Subscription]] = relationship(
        back_populates="user", lazy="selectin", cascade="all, delete-orphan"
    )

    @property
    def mention(self) -> str:
        title = self.first_name or self.username or str(self.telegram_id)
        return f'<a href="tg://user?id={self.telegram_id}">{title}</a>'


class Server(Base, TimestampMixin):
    __tablename__ = "servers"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    country_name: Mapped[str] = mapped_column(String(64), nullable=False)
    country_flag: Mapped[str] = mapped_column(String(16), default="")
    xui_base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    xui_username: Mapped[str] = mapped_column(String(128), nullable=False)
    xui_password: Mapped[str] = mapped_column(String(512), nullable=False)
    server_host: Mapped[str] = mapped_column(String(255), nullable=False)
    inbound_id: Mapped[int] = mapped_column(Integer, nullable=False)
    sub_url: Mapped[str | None] = mapped_column(String(255))
    protocol: Mapped[str] = mapped_column(String(32), default="vless-reality")
    max_clients: Mapped[int] = mapped_column(Integer, default=300)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    subscriptions: Mapped[list[Subscription]] = relationship(back_populates="server")

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
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Subscription(Base, TimestampMixin):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id", ondelete="RESTRICT"))
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("plans.id", ondelete="SET NULL"))

    xui_client_uuid: Mapped[str] = mapped_column(String(64), nullable=False)
    xui_email: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    xui_sub_id: Mapped[str] = mapped_column(String(64), default="")
    xui_inbound_id: Mapped[int] = mapped_column(Integer, nullable=False)

    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus, native_enum=False, length=16),
        default=SubscriptionStatus.active,
        nullable=False,
        index=True,
    )
    device_limit: Mapped[int] = mapped_column(Integer, default=3)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    traffic_used_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    last_synced_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    last_reissued_at: Mapped[datetime | None] = mapped_column(UtcDateTime)

    notified_3d: Mapped[bool] = mapped_column(Boolean, default=False)
    notified_1d: Mapped[bool] = mapped_column(Boolean, default=False)
    notified_3h: Mapped[bool] = mapped_column(Boolean, default=False)
    notified_expired: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped[User] = relationship(back_populates="subscriptions", lazy="selectin")
    server: Mapped[Server] = relationship(back_populates="subscriptions", lazy="selectin")
    plan: Mapped[Plan | None] = relationship(lazy="selectin")

    @property
    def is_active(self) -> bool:
        return self.status is SubscriptionStatus.active


class Payment(Base, TimestampMixin):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("external_id", name="uq_payments_external_id"),
        Index("ix_payments_user_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("plans.id", ondelete="SET NULL"))
    subscription_id: Mapped[int | None] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="SET NULL")
    )
    server_id: Mapped[int | None] = mapped_column(ForeignKey("servers.id", ondelete="SET NULL"))

    provider: Mapped[PaymentProvider] = mapped_column(
        Enum(PaymentProvider, native_enum=False, length=16), nullable=False
    )
    amount_kopeks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    amount_stars: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="RUB")
    external_id: Mapped[str | None] = mapped_column(String(128))
    code: Mapped[str | None] = mapped_column(String(16), index=True)
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, native_enum=False, length=24),
        default=PaymentStatus.pending,
        nullable=False,
        index=True,
    )
    receipt_file_id: Mapped[str | None] = mapped_column(String(256))
    admin_id: Mapped[int | None] = mapped_column(BigInteger)
    promo_code: Mapped[str | None] = mapped_column(String(32))
    bonus_days: Mapped[int] = mapped_column(Integer, default=0)
    provision_attempts: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict | None] = mapped_column(JSON, default=dict)
    paid_at: Mapped[datetime | None] = mapped_column(UtcDateTime)

    user: Mapped[User] = relationship(lazy="selectin")
    plan: Mapped[Plan | None] = relationship(lazy="selectin")


class PromoCode(Base, TimestampMixin):
    __tablename__ = "promo_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    type: Mapped[PromoType] = mapped_column(Enum(PromoType, native_enum=False, length=16))
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    max_uses: Mapped[int] = mapped_column(Integer, default=0)  # 0 = без лимита
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class PromoUse(Base, TimestampMixin):
    __tablename__ = "promo_uses"
    __table_args__ = (UniqueConstraint("promo_id", "user_id", name="uq_promo_uses_promo_id_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    promo_id: Mapped[int] = mapped_column(ForeignKey("promo_codes.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    payment_id: Mapped[int | None] = mapped_column(ForeignKey("payments.id", ondelete="SET NULL"))


class Referral(Base, TimestampMixin):
    __tablename__ = "referrals"

    id: Mapped[int] = mapped_column(primary_key=True)
    referrer_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    referee_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    payment_id: Mapped[int | None] = mapped_column(ForeignKey("payments.id", ondelete="SET NULL"))
    reward_kopeks: Mapped[int] = mapped_column(Integer, default=0)
    paid: Mapped[bool] = mapped_column(Boolean, default=False)


class SupportTicket(Base, TimestampMixin):
    __tablename__ = "support_tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    message: Mapped[str] = mapped_column(Text, default="")
    answered: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_telegram_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict | None] = mapped_column(JSON, default=dict)
