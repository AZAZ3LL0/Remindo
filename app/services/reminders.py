"""Reminder lifecycle: creation, pause, resume, delete."""

from collections.abc import Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import Clock
from app.db.models import Reminder, ReminderRecipient
from app.db.repositories.categories import CategoriesRepository
from app.db.repositories.occurrences import OccurrencesRepository
from app.db.repositories.reminders import RecipientsRepository, RemindersRepository
from app.domain.contracts import RecipientRole, ReminderStatus, ScheduleKind
from app.domain.errors import (
    NotFoundError,
    PermissionDeniedError,
    ScheduleExhaustedError,
    ValidationError,
)
from app.domain.reminders import first_fire_at, normalize_note, normalize_reminder_title
from app.domain.schedules import Schedule, dump_schedule, parse_schedule


class RemindersService:
    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self._session = session
        self._clock = clock
        self._reminders = RemindersRepository(session)
        self._recipients = RecipientsRepository(session)
        self._categories = CategoriesRepository(session)
        self._occurrences = OccurrencesRepository(session)

    async def create(
        self,
        owner_id: int,
        category_id: int,
        title: str,
        schedule: Schedule,
        timezone: str,
        starts_at: datetime | None = None,
        ends_at: datetime | None = None,
        note: str | None = None,
        max_occurrences: int | None = None,
        snooze_minutes: int = 10,
        repeat_after_minutes: int | None = None,
    ) -> Reminder:
        clean_title = normalize_reminder_title(title)
        clean_note = normalize_note(note)
        try:
            tz = ZoneInfo(timezone)  # raises for an unknown IANA name
        except (ValueError, KeyError) as exc:
            raise ValidationError(f"unknown timezone: {timezone!r}") from exc

        # A schedule with nothing ahead of it is never materialised, so the row
        # would look alive and never fire (tech.md 18.6).
        begins_at = starts_at or self._clock.now()
        if first_fire_at(schedule, tz, begins_at) is None:
            raise ScheduleExhaustedError("schedule has no firing moment ahead")

        category = await self._categories.get_by_id(category_id)
        if category is None or category.archived_at is not None:
            raise NotFoundError(f"category {category_id} not found")
        if category.owner_id is not None and category.owner_id != owner_id:
            raise PermissionDeniedError("category belongs to another user")

        reminder = await self._reminders.add(
            Reminder(
                owner_id=owner_id,
                category_id=category_id,
                title=clean_title,
                note=clean_note,
                status=ReminderStatus.ACTIVE,
                schedule_kind=schedule.kind,
                schedule=dump_schedule(schedule),
                timezone=timezone,
                starts_at=begins_at,
                ends_at=ends_at,
                max_occurrences=max_occurrences,
                snooze_minutes=snooze_minutes,
                repeat_after_minutes=repeat_after_minutes,
            )
        )
        await self._recipients.add(
            ReminderRecipient(
                reminder_id=reminder.id,
                user_id=owner_id,
                role=RecipientRole.OWNER,
                accepted_at=self._clock.now(),
            )
        )
        await self._session.commit()
        return reminder

    def next_fire(self, reminder: Reminder) -> datetime | None:
        """When the reminder fires next, for a card drawn before the planner ran.

        Read from the schedule rather than from `occurrences`: right after
        creation the queue is still empty, and the card would say "not
        scheduled" about a reminder that is scheduled.
        """
        after = max(reminder.starts_at, self._clock.now())
        return first_fire_at(parse_schedule(reminder.schedule), ZoneInfo(reminder.timezone), after)

    async def get_owned(self, owner_id: int, reminder_id: int) -> Reminder:
        reminder = await self._reminders.get_by_id(reminder_id)
        if reminder is None:
            raise NotFoundError(f"reminder {reminder_id} not found")
        if reminder.owner_id != owner_id:
            raise PermissionDeniedError("reminder belongs to another user")
        return reminder

    async def list_for_owner(
        self, owner_id: int, page: int, page_size: int, category_id: int | None = None
    ) -> tuple[Sequence[Reminder], int]:
        items = await self._reminders.list_by_owner(
            owner_id, limit=page_size, offset=page * page_size, category_id=category_id
        )
        total = await self._reminders.count_by_owner(owner_id, category_id=category_id)
        return items, total

    async def get_editable(self, owner_id: int, reminder_id: int) -> Reminder:
        """The reminder, refusing an archived one (tech.md 21.4).

        The list never shows archived reminders, so a press can only arrive
        from a stale screen, and a stale press must not revive a reminder the
        planner has finished with.
        """
        reminder = await self.get_owned(owner_id, reminder_id)
        if reminder.status is ReminderStatus.ARCHIVED:
            raise PermissionDeniedError(f"reminder {reminder_id} is archived")
        return reminder

    async def set_status(self, owner_id: int, reminder_id: int, status: ReminderStatus) -> Reminder:
        """Pause or resume. Leaving `active` empties the queue (tech.md 21.3)."""
        reminder = await self.get_editable(owner_id, reminder_id)
        reminder.status = status
        if status is not ReminderStatus.ACTIVE:
            await self._drop_queued(reminder)
        await self._session.commit()
        return reminder

    async def update(
        self,
        owner_id: int,
        reminder_id: int,
        *,
        title: str | None = None,
        note: str | None = None,
        clear_note: bool = False,
        category_id: int | None = None,
        schedule: Schedule | None = None,
        snooze_minutes: int | None = None,
        repeat_after_minutes: int | None = None,
        clear_repeat: bool = False,
    ) -> Reminder:
        """Change one field of a reminder (tech.md 21.4).

        `clear_note` and `clear_repeat` exist because `None` already means "do
        not touch this field": without them, emptying a note and leaving it
        alone would be the same call.
        """
        reminder = await self.get_editable(owner_id, reminder_id)

        if title is not None:
            reminder.title = normalize_reminder_title(title)
        if clear_note:
            reminder.note = None
        elif note is not None:
            reminder.note = normalize_note(note)
        if snooze_minutes is not None:
            reminder.snooze_minutes = snooze_minutes
        if clear_repeat:
            reminder.repeat_after_minutes = None
        elif repeat_after_minutes is not None:
            reminder.repeat_after_minutes = repeat_after_minutes
        if category_id is not None:
            reminder.category_id = await self._checked_category(owner_id, category_id)
        if schedule is not None:
            await self._replace_schedule(reminder, schedule)

        await self._session.commit()
        return reminder

    async def _checked_category(self, owner_id: int, category_id: int) -> int:
        """The same gate creation passes (tech.md 21.4)."""
        category = await self._categories.get_by_id(category_id)
        if category is None or category.archived_at is not None:
            raise NotFoundError(f"category {category_id} not found")
        if category.owner_id is not None and category.owner_id != owner_id:
            raise PermissionDeniedError("category belongs to another user")
        return category_id

    async def _replace_schedule(self, reminder: Reminder, schedule: Schedule) -> None:
        """Swap the schedule, refusing one with nothing ahead of it.

        The timezone stays as it was: it is the snapshot the old schedule was
        expanded in (tech.md 21.4), and swapping it would move every future
        moment without saying so.
        """
        tz = ZoneInfo(reminder.timezone)
        after = max(reminder.starts_at, self._clock.now())
        if first_fire_at(schedule, tz, after) is None:
            raise ScheduleExhaustedError("schedule has no firing moment ahead")

        reminder.schedule_kind = ScheduleKind(schedule.kind)
        reminder.schedule = dump_schedule(schedule)
        # What was queued belongs to the schedule that just went away.
        await self._drop_queued(reminder)

    async def _drop_queued(self, reminder: Reminder) -> None:
        """Take back the occurrences nothing has been sent for (tech.md 21.3).

        Idempotent: called twice, the second call removes nothing and changes
        nothing else.
        """
        dropped = await self._occurrences.delete_unsent(reminder.id)
        await self._reminders.reset_planning(reminder.id, reminder.fired_count - dropped)
        reminder.planned_until = None
        reminder.fired_count = max(reminder.fired_count - dropped, 0)

    async def delete(self, owner_id: int, reminder_id: int) -> None:
        reminder = await self.get_owned(owner_id, reminder_id)
        await self._session.delete(reminder)
        await self._session.commit()
