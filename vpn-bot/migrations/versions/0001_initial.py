"""initial schema

Revision ID: 0001
Revises:
Create Date: 2025-01-01

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


SUBSCRIPTION_STATUS = sa.Enum(
    "active", "expired", "disabled", "deleted", name="subscription_status", native_enum=False
)
PAYMENT_PROVIDER = sa.Enum(
    "yookassa", "stars", "manual", "balance", name="payment_provider", native_enum=False
)
PAYMENT_STATUS = sa.Enum(
    "pending", "paid", "failed", "refunded", "canceled", name="payment_status", native_enum=False
)
PROVISION_STATUS = sa.Enum(
    "none", "pending", "failed", "done", name="provision_status", native_enum=False
)
PROMO_TYPE = sa.Enum("percent", "fixed", "days", name="promo_type", native_enum=False)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("first_name", sa.String(length=128), nullable=True),
        sa.Column("language_code", sa.String(length=8), nullable=False),
        sa.Column("referrer_id", sa.Integer(), nullable=True),
        sa.Column("balance_kopeks", sa.Integer(), nullable=False),
        sa.Column("trial_used", sa.Boolean(), nullable=False),
        sa.Column("is_banned", sa.Boolean(), nullable=False),
        sa.Column("is_reachable", sa.Boolean(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["referrer_id"], ["users.id"], name="fk_users_referrer_id_users", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("telegram_id", name="uq_users_telegram_id"),
    )
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"])
    op.create_index("ix_users_referrer_id", "users", ["referrer_id"])

    op.create_table(
        "servers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("country_name", sa.String(length=64), nullable=False),
        sa.Column("country_flag", sa.String(length=8), nullable=False),
        sa.Column("xui_base_url", sa.String(length=512), nullable=False),
        sa.Column("xui_username", sa.String(length=128), nullable=False),
        sa.Column("xui_password", sa.String(length=512), nullable=False),
        sa.Column("server_host", sa.String(length=255), nullable=False),
        sa.Column("inbound_id", sa.Integer(), nullable=False),
        sa.Column("sub_url", sa.String(length=512), nullable=True),
        sa.Column("protocol", sa.String(length=32), nullable=False),
        sa.Column("max_clients", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_servers"),
        sa.UniqueConstraint("code", name="uq_servers_code"),
    )

    op.create_table(
        "plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=64), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("price_kopeks", sa.Integer(), nullable=False),
        sa.Column("price_stars", sa.Integer(), nullable=False),
        sa.Column("device_limit", sa.Integer(), nullable=False),
        sa.Column("is_trial", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_plans"),
        sa.UniqueConstraint("code", name="uq_plans_code"),
    )

    op.create_table(
        "promo_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("type", PROMO_TYPE, nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=False),
        sa.Column("used_count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_promo_codes"),
        sa.UniqueConstraint("code", name="uq_promo_codes_code"),
    )

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("server_id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("xui_client_uuid", sa.String(length=64), nullable=False),
        sa.Column("xui_email", sa.String(length=128), nullable=False),
        sa.Column("xui_sub_id", sa.String(length=64), nullable=False),
        sa.Column("xui_inbound_id", sa.Integer(), nullable=False),
        sa.Column("status", SUBSCRIPTION_STATUS, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("traffic_used_bytes", sa.BigInteger(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reissued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notified_3d", sa.Boolean(), nullable=False),
        sa.Column("notified_1d", sa.Boolean(), nullable=False),
        sa.Column("notified_3h", sa.Boolean(), nullable=False),
        sa.Column("notified_expired", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_subscriptions_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["server_id"],
            ["servers.id"],
            name="fk_subscriptions_server_id_servers",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["plans.id"], name="fk_subscriptions_plan_id_plans", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_subscriptions"),
        sa.UniqueConstraint("xui_email", name="uq_subscriptions_xui_email"),
    )
    op.create_index("ix_subscriptions_user_id", "subscriptions", ["user_id"])
    op.create_index("ix_subscriptions_server_id", "subscriptions", ["server_id"])
    op.create_index("ix_subscriptions_plan_id", "subscriptions", ["plan_id"])
    op.create_index(
        "ix_subscriptions_status_expires", "subscriptions", ["status", "expires_at"]
    )

    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("subscription_id", sa.Integer(), nullable=True),
        sa.Column("server_id", sa.Integer(), nullable=True),
        sa.Column("provider", PAYMENT_PROVIDER, nullable=False),
        sa.Column("amount_kopeks", sa.Integer(), nullable=False),
        sa.Column("amount_stars", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=True),
        sa.Column("code", sa.String(length=16), nullable=True),
        sa.Column("status", PAYMENT_STATUS, nullable=False),
        sa.Column("provision_status", PROVISION_STATUS, nullable=False),
        sa.Column("provision_attempts", sa.Integer(), nullable=False),
        sa.Column("provision_next_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("promo_id", sa.Integer(), nullable=True),
        sa.Column("discount_kopeks", sa.Integer(), nullable=False),
        sa.Column("bonus_days", sa.Integer(), nullable=False),
        sa.Column("renew_subscription_id", sa.Integer(), nullable=True),
        sa.Column("receipt_file_id", sa.String(length=256), nullable=True),
        sa.Column("admin_id", sa.BigInteger(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_payments_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["plans.id"], name="fk_payments_plan_id_plans", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["subscriptions.id"],
            name="fk_payments_subscription_id_subscriptions",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["renew_subscription_id"],
            ["subscriptions.id"],
            name="fk_payments_renew_subscription_id_subscriptions",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["server_id"], ["servers.id"], name="fk_payments_server_id_servers", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["promo_id"],
            ["promo_codes.id"],
            name="fk_payments_promo_id_promo_codes",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_payments"),
        sa.UniqueConstraint("external_id", name="uq_payments_external_id"),
    )
    op.create_index("ix_payments_user_id", "payments", ["user_id"])
    op.create_index("ix_payments_code", "payments", ["code"])
    op.create_index("ix_payments_status_created", "payments", ["status", "created_at"])

    op.create_table(
        "promo_uses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("promo_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("payment_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["promo_id"],
            ["promo_codes.id"],
            name="fk_promo_uses_promo_id_promo_codes",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_promo_uses_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["payment_id"],
            ["payments.id"],
            name="fk_promo_uses_payment_id_payments",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_promo_uses"),
        sa.UniqueConstraint("promo_id", "user_id", name="uq_promo_uses_promo_id_user"),
    )

    op.create_table(
        "referrals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("referrer_id", sa.Integer(), nullable=False),
        sa.Column("referee_id", sa.Integer(), nullable=False),
        sa.Column("payment_id", sa.Integer(), nullable=True),
        sa.Column("reward_kopeks", sa.Integer(), nullable=False),
        sa.Column("paid", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["referrer_id"], ["users.id"], name="fk_referrals_referrer_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["referee_id"], ["users.id"], name="fk_referrals_referee_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["payment_id"],
            ["payments.id"],
            name="fk_referrals_payment_id_payments",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_referrals"),
        sa.UniqueConstraint("payment_id", name="uq_referrals_payment_id"),
    )
    op.create_index("ix_referrals_referrer_id", "referrals", ["referrer_id"])
    op.create_index("ix_referrals_referee_id", "referrals", ["referee_id"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor_telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity", sa.String(length=64), nullable=True),
        sa.Column("entity_id", sa.String(length=64), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_audit_log"),
    )
    op.create_index("ix_audit_log_actor_telegram_id", "audit_log", ["actor_telegram_id"])

    op.create_table(
        "support_tickets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("answered", sa.Boolean(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("admin_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_support_tickets_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_support_tickets"),
    )


def downgrade() -> None:
    op.drop_table("support_tickets")
    op.drop_index("ix_audit_log_actor_telegram_id", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index("ix_referrals_referee_id", table_name="referrals")
    op.drop_index("ix_referrals_referrer_id", table_name="referrals")
    op.drop_table("referrals")
    op.drop_table("promo_uses")
    op.drop_index("ix_payments_status_created", table_name="payments")
    op.drop_index("ix_payments_code", table_name="payments")
    op.drop_index("ix_payments_user_id", table_name="payments")
    op.drop_table("payments")
    op.drop_index("ix_subscriptions_status_expires", table_name="subscriptions")
    op.drop_index("ix_subscriptions_plan_id", table_name="subscriptions")
    op.drop_index("ix_subscriptions_server_id", table_name="subscriptions")
    op.drop_index("ix_subscriptions_user_id", table_name="subscriptions")
    op.drop_table("subscriptions")
    op.drop_table("promo_codes")
    op.drop_table("plans")
    op.drop_table("servers")
    op.drop_index("ix_users_referrer_id", table_name="users")
    op.drop_index("ix_users_telegram_id", table_name="users")
    op.drop_table("users")
