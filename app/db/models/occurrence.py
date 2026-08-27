from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import OCCURRENCE_STATUS, Base, TimestampMixin
from app.domain.contracts import OccurrenceStatus


class Occurrence(Base, TimestampMixin):
    """One planned firing. This table is the queue."""

    __tablename__ = "occurrences"
    __table_args__ = (
        sa.UniqueConstraint(
            "reminder_id", "scheduled_for", name="uq_occurrences_reminder_scheduled"
        ),
        sa.Index(
            "ix_occurrences_fire_at_pending",
            "fire_at",
            postgresql_where=sa.text("status = 'pending'"),
        ),
    )

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    reminder_id: Mapped[int] = mapped_column(
        sa.BigInteger, sa.ForeignKey("reminders.id", ondelete="CASCADE"), nullable=False
    )
    scheduled_for: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True), nullable=False)
    fire_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True), nullable=False)
    status: Mapped[OccurrenceStatus] = mapped_column(
        OCCURRENCE_STATUS, nullable=False, server_default=OccurrenceStatus.PENDING.value
    )
    repeats_sent: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False, server_default="0")
    expires_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True), nullable=False)
