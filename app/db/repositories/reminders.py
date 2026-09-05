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

    async def reset_planning(self, reminder_id: int, fired_count: int) -> None:
        """Forget the materialised horizon (tech.md 21.3).

        `planned_until` goes back to NULL: left in place, the planner would
        think the horizon is already covered and materialise nothing until it
        runs out.
        """
        stmt = (
            sa.update(Reminder)
            .where(Reminder.id == reminder_id)
            .values(planned_until=None, fired_count=max(fired_count, 0))
        )
        await self._session.execute(stmt)

    async def update_fields(self, reminder_id: int, **values: object) -> None:
        stmt = sa.update(Reminder).where(Reminder.id == reminder_id).values(**values)
        await self._session.execute(stmt)

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

    async def get(self, reminder_id: int, user_id: int) -> ReminderRecipient | None:
        stmt = sa.select(ReminderRecipient).where(
            ReminderRecipient.reminder_id == reminder_id,
            ReminderRecipient.user_id == user_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def count_watchers(self, reminder_id: int) -> int:
        """Recipients other than the owner, accepted or still deciding.

        A pending row counts: it holds a place the limit of tech.md 22.4 is
        there to protect, and a link that hands out unlimited pending rows is
        the same amplifier as one that hands out unlimited watchers.
        """
        stmt = sa.select(sa.func.count()).where(
            ReminderRecipient.reminder_id == reminder_id,
            ReminderRecipient.role == RecipientRole.WATCHER,
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def count_accepted_watchers(self, reminder_id: int) -> int:
        """Watchers the reminder actually reaches, for the owner's card."""
        stmt = sa.select(sa.func.count()).where(
            ReminderRecipient.reminder_id == reminder_id,
            ReminderRecipient.role == RecipientRole.WATCHER,
            ReminderRecipient.accepted_at.is_not(None),
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def list_for_reminder(self, reminder_id: int) -> Sequence[ReminderRecipient]:
        stmt = (
            sa.select(ReminderRecipient)
            .where(ReminderRecipient.reminder_id == reminder_id)
            .order_by(ReminderRecipient.id)
        )
        return (await self._session.execute(stmt)).scalars().all()

    async def list_shared_with(
        self, user_id: int, limit: int, offset: int
    ) -> Sequence[tuple[ReminderRecipient, Reminder]]:
        """Reminders somebody else shares with this user, pending ones included.

        Archived reminders are left out for the same reason the owner's list
        leaves them out (tech.md 21.4): nothing there fires again.
        """
        stmt = (
            sa.select(ReminderRecipient, Reminder)
            .join(Reminder, Reminder.id == ReminderRecipient.reminder_id)
            .where(
                ReminderRecipient.user_id == user_id,
                ReminderRecipient.role == RecipientRole.WATCHER,
                Reminder.status != ReminderStatus.ARCHIVED,
            )
            .order_by(ReminderRecipient.id)
            .limit(limit)
            .offset(offset)
        )
        return list((await self._session.execute(stmt)).tuples().all())

    async def count_shared_with(self, user_id: int) -> int:
        stmt = (
            sa.select(sa.func.count())
            .select_from(ReminderRecipient)
            .join(Reminder, Reminder.id == ReminderRecipient.reminder_id)
            .where(
                ReminderRecipient.user_id == user_id,
                ReminderRecipient.role == RecipientRole.WATCHER,
                Reminder.status != ReminderStatus.ARCHIVED,
            )
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def accept(self, reminder_id: int, user_id: int, now: datetime) -> int:
        """Mark a pending recipient as accepted.

        Only a pending row is touched, so a second press changes nothing and
        does not move the moment the first press recorded.
        """
        stmt = (
            sa.update(ReminderRecipient)
            .where(
                ReminderRecipient.reminder_id == reminder_id,
                ReminderRecipient.user_id == user_id,
                ReminderRecipient.role == RecipientRole.WATCHER,
                ReminderRecipient.accepted_at.is_(None),
            )
            .values(accepted_at=now)
            .returning(ReminderRecipient.id)
        )
        return len((await self._session.execute(stmt)).scalars().all())

    async def remove_watcher(self, reminder_id: int, user_id: int) -> int:
        """Drop a watcher row. The owner's row is never a candidate."""
        stmt = (
            sa.delete(ReminderRecipient)
            .where(
                ReminderRecipient.reminder_id == reminder_id,
                ReminderRecipient.user_id == user_id,
                ReminderRecipient.role == RecipientRole.WATCHER,
            )
            .returning(ReminderRecipient.id)
        )
        return len((await self._session.execute(stmt)).scalars().all())
