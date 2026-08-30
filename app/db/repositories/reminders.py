"""Reminder and recipient queries."""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Reminder, ReminderRecipient
from app.domain.contracts import RecipientRole, ReminderStatus


class RemindersRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, reminder_id: int) -> Reminder | None:
        return await self._session.get(Reminder, reminder_id)

    async def add(self, reminder: Reminder) -> Reminder:
        self._session.add(reminder)
        await self._session.flush()
        return reminder

    async def list_by_owner(
        self, owner_id: int, limit: int, offset: int, category_id: int | None = None
    ) -> Sequence[Reminder]:
        stmt = sa.select(Reminder).where(
            Reminder.owner_id == owner_id,
            Reminder.status != ReminderStatus.ARCHIVED,
        )
        if category_id is not None:
            stmt = stmt.where(Reminder.category_id == category_id)
        stmt = stmt.order_by(Reminder.id).limit(limit).offset(offset)
        return (await self._session.execute(stmt)).scalars().all()

    async def count_by_owner(self, owner_id: int, category_id: int | None = None) -> int:
        stmt = sa.select(sa.func.count()).where(
            Reminder.owner_id == owner_id,
            Reminder.status != ReminderStatus.ARCHIVED,
        )
        if category_id is not None:
            stmt = stmt.where(Reminder.category_id == category_id)
        return int((await self._session.execute(stmt)).scalar_one())

    async def due_for_planning(self, horizon_end: datetime, limit: int) -> Sequence[Reminder]:
        """Active reminders whose materialised horizon is about to run out.

        Least planned first, so a batch smaller than the backlog cannot starve
        the same tail of reminders cycle after cycle. The order matches the
        partial index on (status, planned_until).
        """
        stmt = (
            sa.select(Reminder)
            .where(
                Reminder.status == ReminderStatus.ACTIVE,
                Reminder.starts_at <= horizon_end,
                sa.or_(
                    Reminder.planned_until.is_(None),
                    Reminder.planned_until < horizon_end,
                ),
            )
            .order_by(sa.nulls_first(Reminder.planned_until.asc()), Reminder.id)
            .limit(limit)
        )
        return (await self._session.execute(stmt)).scalars().all()

    async def set_planning_state(
        self, reminder_id: int, planned_until: datetime, fired_count: int
    ) -> None:
        stmt = (
            sa.update(Reminder)
            .where(Reminder.id == reminder_id)
            .values(planned_until=planned_until, fired_count=fired_count)
        )
        await self._session.execute(stmt)

    async def set_status(self, reminder_id: int, status: ReminderStatus) -> None:
        stmt = sa.update(Reminder).where(Reminder.id == reminder_id).values(status=status)
        await self._session.execute(stmt)


class RecipientsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, recipient: ReminderRecipient) -> ReminderRecipient:
        self._session.add(recipient)
        await self._session.flush()
        return recipient

    async def list_accepted_user_ids(self, reminder_id: int) -> Sequence[int]:
        """Recipients the dispatcher may write to. The owner always accepts."""
        stmt = sa.select(ReminderRecipient.user_id).where(
            ReminderRecipient.reminder_id == reminder_id,
            sa.or_(
                ReminderRecipient.role == RecipientRole.OWNER,
                ReminderRecipient.accepted_at.is_not(None),
            ),
        )
        return (await self._session.execute(stmt)).scalars().all()
