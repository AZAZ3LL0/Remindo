"""Declarative base, constraint naming and shared enum types."""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.domain.contracts import (
    ActionKind,
    DeliveryStatus,
    OccurrenceStatus,
    RecipientRole,
    ReminderStatus,
    ScheduleKind,
)

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def _pg_enum(enum_cls: type, name: str) -> sa.Enum:
    """Native PostgreSQL enum built from the domain enum values."""
    return sa.Enum(
        enum_cls,
        name=name,
        native_enum=True,
        values_callable=lambda enum: [member.value for member in enum],
    )


REMINDER_STATUS = _pg_enum(ReminderStatus, "reminder_status")
SCHEDULE_KIND = _pg_enum(ScheduleKind, "schedule_kind")
OCCURRENCE_STATUS = _pg_enum(OccurrenceStatus, "occurrence_status")
DELIVERY_STATUS = _pg_enum(DeliveryStatus, "delivery_status")
RECIPIENT_ROLE = _pg_enum(RecipientRole, "recipient_role")
ACTION_KIND = _pg_enum(ActionKind, "action_kind")


class Base(DeclarativeBase):
    metadata = sa.MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )
