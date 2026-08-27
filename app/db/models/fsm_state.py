from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FSMState(Base):
    """aiogram FSM storage, so the creation wizard survives a restart."""

    __tablename__ = "fsm_states"

    key: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    state: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )
