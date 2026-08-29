from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import REMINDER_STATUS, SCHEDULE_KIND, Base, TimestampMixin
from app.domain.contracts import ReminderStatus, ScheduleKind


class Reminder(Base, TimestampMixin):
    __tablename__ = "reminders"
    __table_args__ = (
        sa.CheckConstraint("ends_at IS NULL OR ends_at > starts_at", name="ends_after_start"),
        sa.CheckConstraint(
            "schedule_kind::text = schedule->>'kind'", name="schedule_kind_matches_payload"
        ),
        sa.CheckConstraint("char_length(title) BETWEEN 1 AND 120", name="title_length"),
        sa.CheckConstraint("note IS NULL OR char_length(note) <= 1000", name="note_length"),
        sa.Index(
            "ix_reminders_status_planned_until",
            "status",
            "planned_until",
            postgresql_where=sa.text("status = 'active'"),
        ),
        sa.Index("ix_reminders_owner_id_status", "owner_id", "status"),
    )

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(
        sa.BigInteger, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[int] = mapped_column(
        sa.BigInteger, sa.ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(sa.Text, nullable=False)
    note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    status: Mapped[ReminderStatus] = mapped_column(
        REMINDER_STATUS, nullable=False, server_default=ReminderStatus.ACTIVE.value
    )
    schedule_kind: Mapped[ScheduleKind] = mapped_column(SCHEDULE_KIND, nullable=False)
    schedule: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    timezone: Mapped[str] = mapped_column(sa.Text, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True), nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(sa.TIMESTAMP(timezone=True), nullable=True)
    max_occurrences: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    fired_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default="0")
    snooze_minutes: Mapped[int] = mapped_column(
        sa.SmallInteger, nullable=False, server_default="10"
    )
    repeat_after_minutes: Mapped[int | None] = mapped_column(sa.SmallInteger, nullable=True)
    max_repeats: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False, server_default="2")
    planned_until: Mapped[datetime | None] = mapped_column(
        sa.TIMESTAMP(timezone=True), nullable=True
    )
