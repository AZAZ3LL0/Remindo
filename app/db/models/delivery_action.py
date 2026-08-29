from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import ACTION_KIND, Base
from app.domain.contracts import ActionKind


class DeliveryAction(Base):
    """Append-only reaction journal. Rows are never updated or deleted."""

    __tablename__ = "delivery_actions"
    __table_args__ = (sa.Index("ix_delivery_actions_delivery_id", "delivery_id"),)

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    delivery_id: Mapped[int] = mapped_column(
        sa.BigInteger, sa.ForeignKey("deliveries.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        sa.BigInteger, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[ActionKind] = mapped_column(ACTION_KIND, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False
    )
