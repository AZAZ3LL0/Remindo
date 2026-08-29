"""Initial schema: users, categories, reminders and the delivery queue

Revision ID: 2220d8c847bd
Revises:
Create Date: 2026-08-27 19:35:35.253293
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2220d8c847bd"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENUM_NAMES = (
    "reminder_status",
    "schedule_kind",
    "occurrence_status",
    "delivery_status",
    "recipient_role",
    "action_kind",
)


def upgrade() -> None:
    op.create_table(
        "fsm_states",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=True),
        sa.Column(
            "data",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_fsm_states")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=False),
        sa.Column("tg_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.Text(), nullable=True),
        sa.Column("first_name", sa.Text(), server_default="", nullable=False),
        sa.Column("language", sa.Text(), server_default="ru", nullable=False),
        sa.Column("timezone", sa.Text(), server_default="Europe/Moscow", nullable=False),
        sa.Column("quiet_start", sa.Time(), nullable=True),
        sa.Column("quiet_end", sa.Time(), nullable=True),
        sa.Column("is_blocked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("onboarded_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(quiet_start IS NULL) = (quiet_end IS NULL)",
            name=op.f("ck_users_quiet_hours_both_or_none"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("tg_user_id", name=op.f("uq_users_tg_user_id")),
    )
    op.create_table(
        "categories",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=True),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("emoji", sa.Text(), server_default="🔔", nullable=False),
        sa.Column("is_system", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("sort_order", sa.SmallInteger(), server_default="100", nullable=False),
        sa.Column("archived_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("code ~ '^[a-z0-9_]{2,32}$'", name=op.f("ck_categories_code_is_slug")),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_categories_owner_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categories")),
    )
    op.create_index(
        "ix_categories_owner_id_active",
        "categories",
        ["owner_id"],
        unique=False,
        postgresql_where=sa.text("archived_at IS NULL"),
    )
    op.create_index(
        "uq_categories_code_system",
        "categories",
        ["code"],
        unique=True,
        postgresql_where=sa.text("owner_id IS NULL"),
    )
    op.create_index(
        "uq_categories_owner_id_code",
        "categories",
        ["owner_id", "code"],
        unique=True,
        postgresql_where=sa.text("owner_id IS NOT NULL"),
    )
    op.create_table(
        "reminders",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("category_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("active", "paused", "archived", name="reminder_status"),
            server_default="active",
            nullable=False,
        ),
        sa.Column(
            "schedule_kind",
            sa.Enum("once", "interval", "daily", "weekly", "monthly", name="schedule_kind"),
            nullable=False,
        ),
        sa.Column("schedule", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("timezone", sa.Text(), nullable=False),
        sa.Column("starts_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("ends_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("max_occurrences", sa.Integer(), nullable=True),
        sa.Column("fired_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("snooze_minutes", sa.SmallInteger(), server_default="10", nullable=False),
        sa.Column("repeat_after_minutes", sa.SmallInteger(), nullable=True),
        sa.Column("max_repeats", sa.SmallInteger(), server_default="2", nullable=False),
        sa.Column("planned_until", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "schedule_kind::text = schedule->>'kind'",
            name=op.f("ck_reminders_schedule_kind_matches_payload"),
        ),
        sa.CheckConstraint(
            "char_length(title) BETWEEN 1 AND 120", name=op.f("ck_reminders_title_length")
        ),
        sa.CheckConstraint(
            "ends_at IS NULL OR ends_at > starts_at", name=op.f("ck_reminders_ends_after_start")
        ),
        sa.CheckConstraint(
            "note IS NULL OR char_length(note) <= 1000", name=op.f("ck_reminders_note_length")
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_reminders_category_id_categories"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_reminders_owner_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reminders")),
    )
    op.create_index(
        "ix_reminders_owner_id_status", "reminders", ["owner_id", "status"], unique=False
    )
    op.create_index(
        "ix_reminders_status_planned_until",
        "reminders",
        ["status", "planned_until"],
        unique=False,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_table(
        "occurrences",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("reminder_id", sa.BigInteger(), nullable=False),
        sa.Column("scheduled_for", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("fire_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "dispatching",
                "sent",
                "done",
                "skipped",
                "expired",
                "failed",
                name="occurrence_status",
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("repeats_sent", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["reminder_id"],
            ["reminders.id"],
            name=op.f("fk_occurrences_reminder_id_reminders"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_occurrences")),
        sa.UniqueConstraint(
            "reminder_id", "scheduled_for", name="uq_occurrences_reminder_scheduled"
        ),
    )
    op.create_index(
        "ix_occurrences_fire_at_pending",
        "occurrences",
        ["fire_at"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_table(
        "reminder_recipients",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("reminder_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.Enum("owner", "watcher", name="recipient_role"), nullable=False),
        sa.Column("accepted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["reminder_id"],
            ["reminders.id"],
            name=op.f("fk_reminder_recipients_reminder_id_reminders"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_reminder_recipients_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reminder_recipients")),
        sa.UniqueConstraint("reminder_id", "user_id", name="uq_reminder_recipients_reminder_user"),
    )
    op.create_index(
        "uq_reminder_recipients_single_owner",
        "reminder_recipients",
        ["reminder_id"],
        unique=True,
        postgresql_where=sa.text("role = 'owner'"),
    )
    op.create_table(
        "deliveries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("occurrence_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "sent",
                "done",
                "skipped",
                "snoozed",
                "failed",
                "blocked",
                name="delivery_status",
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("attempts", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("locked_until", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("tg_message_id", sa.BigInteger(), nullable=True),
        sa.Column("sent_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("reacted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("snoozed_until", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["occurrence_id"],
            ["occurrences.id"],
            name=op.f("fk_deliveries_occurrence_id_occurrences"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_deliveries_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deliveries")),
        sa.UniqueConstraint("occurrence_id", "user_id", name="uq_deliveries_occurrence_user"),
    )
    op.create_index(
        "ix_deliveries_next_attempt_at_due",
        "deliveries",
        ["next_attempt_at"],
        unique=False,
        postgresql_where=sa.text("status IN ('pending', 'snoozed')"),
    )
    op.create_table(
        "delivery_actions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("delivery_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("done", "snooze", "skip", "auto_expire", name="action_kind"),
            nullable=False,
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["delivery_id"],
            ["deliveries.id"],
            name=op.f("fk_delivery_actions_delivery_id_deliveries"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_delivery_actions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_delivery_actions")),
    )
    op.create_index(
        "ix_delivery_actions_delivery_id", "delivery_actions", ["delivery_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_delivery_actions_delivery_id", table_name="delivery_actions")
    op.drop_table("delivery_actions")
    op.drop_index(
        "ix_deliveries_next_attempt_at_due",
        table_name="deliveries",
        postgresql_where=sa.text("status IN ('pending', 'snoozed')"),
    )
    op.drop_table("deliveries")
    op.drop_index(
        "uq_reminder_recipients_single_owner",
        table_name="reminder_recipients",
        postgresql_where=sa.text("role = 'owner'"),
    )
    op.drop_table("reminder_recipients")
    op.drop_index(
        "ix_occurrences_fire_at_pending",
        table_name="occurrences",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.drop_table("occurrences")
    op.drop_index(
        "ix_reminders_status_planned_until",
        table_name="reminders",
        postgresql_where=sa.text("status = 'active'"),
    )
    op.drop_index("ix_reminders_owner_id_status", table_name="reminders")
    op.drop_table("reminders")
    op.drop_index(
        "uq_categories_owner_id_code",
        table_name="categories",
        postgresql_where=sa.text("owner_id IS NOT NULL"),
    )
    op.drop_index(
        "uq_categories_code_system",
        table_name="categories",
        postgresql_where=sa.text("owner_id IS NULL"),
    )
    op.drop_index(
        "ix_categories_owner_id_active",
        table_name="categories",
        postgresql_where=sa.text("archived_at IS NULL"),
    )
    op.drop_table("categories")
    op.drop_table("users")
    op.drop_table("fsm_states")
    # Native enum types outlive their tables, so drop them explicitly.
    for enum_name in ENUM_NAMES:
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
