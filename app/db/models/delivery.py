from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import DELIVERY_STATUS, Base, TimestampMixin
from app.domain.contracts import DeliveryStatus


class Delivery(Base, TimestampMixin):
    """Delivery of one occurrence to one recipient."""

    __tablename__ = "deliveries"
    __table_args__ = (
        sa.UniqueConstraint("occurrence_id", "user_id", name="uq_deliveries_occurrence_user"),
        sa.Index(
            "ix_deliveries_next_attempt_at_due",
            "next_attempt_at",
            postgresql_where=sa.text("status IN ('pending', 'snoozed')"),
        ),
    )

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    occurrence_id: Mapped[int] = mapped_column(
        sa.BigInteger, sa.ForeignKey("occurrences.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        sa.BigInteger, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[DeliveryStatus] = mapped_column(
        DELIVERY_STATUS, nullable=False, server_default=DeliveryStatus.PENDING.value
    )
    attempts: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True), nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(
        sa.TIMESTAMP(timezone=True), nullable=True
    )
    tg_message_id: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(sa.TIMESTAMP(timezone=True), nullable=True)
    reacted_at: Mapped[datetime | None] = mapped_column(sa.TIMESTAMP(timezone=True), nullable=True)
    snoozed_until: Mapped[datetime | None] = mapped_column(
        sa.TIMESTAMP(timezone=True), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
