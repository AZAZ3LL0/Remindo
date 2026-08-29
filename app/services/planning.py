"""planner.materialize: turn schedules into queue rows (tech.md 7.1)."""

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import Clock
from app.core.logging import get_logger
from app.db.models import Reminder, User
from app.db.repositories.deliveries import DeliveriesRepository
from app.db.repositories.occurrences import OccurrencesRepository
from app.db.repositories.reminders import RecipientsRepository, RemindersRepository
from app.db.repositories.users import UsersRepository
from app.domain.contracts import OccurrenceStatus, ReminderStatus
from app.domain.planning import (
    PlanBounds,
    PlanWindow,
    last_moment_of,
    plan_window,
    settle_plan,
)
from app.domain.quiet_hours import apply_quiet_hours
from app.domain.recurrence import next_occurrences
from app.domain.schedules import Schedule, parse_schedule

_log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PlanningResult:
    reminders_processed: int = 0
    occurrences_created: int = 0
    deliveries_created: int = 0
    reminders_archived: int = 0


class PlanningService:
    def __init__(
        self,
        session: AsyncSession,
        clock: Clock,
        horizon_hours: int,
        occurrence_ttl_minutes: int,
        batch_size: int = 100,
    ) -> None:
        self._session = session
        self._clock = clock
        self._horizon = timedelta(hours=horizon_hours)
        self._ttl = timedelta(minutes=occurrence_ttl_minutes)
        self._batch_size = batch_size
        self._reminders = RemindersRepository(session)
        self._recipients = RecipientsRepository(session)
        self._occurrences = OccurrencesRepository(session)
        self._deliveries = DeliveriesRepository(session)
        self._users = UsersRepository(session)

    async def materialize(self) -> PlanningResult:
        """One planner cycle. Re-running it on the same input changes nothing."""
        now = self._clock.now()
        horizon_end = now + self._horizon
        due = await self._reminders.due_for_planning(horizon_end, self._batch_size)

        created_occurrences = 0
        created_deliveries = 0
        archived = 0

        for reminder in due:
            owner = await self._users.get_by_id(reminder.owner_id)
            if owner is None:
                continue
            outcome = await self._materialize_one(reminder, owner, horizon_end)
            created_occurrences += outcome[0]
            created_deliveries += outcome[1]
            archived += outcome[2]

        # One commit for the batch: a cycle that dies halfway leaves no reminder
        # holding occurrences without deliveries (tech.md 7.1).
        await self._session.commit()
        result = PlanningResult(
            reminders_processed=len(due),
            occurrences_created=created_occurrences,
            deliveries_created=created_deliveries,
            reminders_archived=archived,
        )
        _log.info("planner.materialize", **asdict(result))
        return result

    async def _materialize_one(
        self, reminder: Reminder, owner: User, horizon_end: datetime
    ) -> tuple[int, int, int]:
        tz = ZoneInfo(reminder.timezone)
        schedule = parse_schedule(reminder.schedule)

        # Counted, not read from the column: the count is what the budget in
        # tech.md 7.1 is spent against, and it survives a column that drifted.
        fired_count = await self._occurrences.count_for_reminder(reminder.id)
        bounds = PlanBounds(
            starts_at=reminder.starts_at,
            planned_until=reminder.planned_until,
            ends_at=reminder.ends_at,
            max_occurrences=reminder.max_occurrences,
            last_moment=last_moment_of(schedule, tz),
        )
        window = plan_window(bounds, horizon_end=horizon_end, fired_count=fired_count)
        moments = self._expand(schedule, tz, window)

        created_occurrences = await self._occurrences.insert_missing(
            self._occurrence_rows(reminder, owner, tz, moments)
        )
        created_deliveries = await self._create_deliveries(reminder, moments)

        fired_count += created_occurrences
        outcome = settle_plan(bounds, window, moments, fired_count)
        await self._reminders.set_planning_state(reminder.id, outcome.planned_until, fired_count)

        archived = 0
        if outcome.exhausted:
            # Materialised occurrences keep their own schedule; archiving only
            # stops the planner from looking at this reminder again.
            await self._reminders.set_status(reminder.id, ReminderStatus.ARCHIVED)
            archived = 1
            _log.info(
                "planner.reminder_exhausted",
                reminder_id=reminder.id,
                fired_count=fired_count,
            )

        return created_occurrences, created_deliveries, archived

    @staticmethod
    def _expand(schedule: Schedule, tz: ZoneInfo, window: PlanWindow) -> list[datetime]:
        if window.is_empty:
            return []
        return next_occurrences(
            schedule, tz, after=window.after, until=window.until, limit=window.limit
        )

    def _occurrence_rows(
        self, reminder: Reminder, owner: User, tz: ZoneInfo, moments: list[datetime]
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for moment in moments:
            # Quiet hours belong to the owner: one occurrence, one fire_at.
            fire_at = apply_quiet_hours(moment, tz, owner.quiet_start, owner.quiet_end)
            rows.append(
                {
                    "reminder_id": reminder.id,
                    "scheduled_for": moment,
                    "fire_at": fire_at,
                    "status": OccurrenceStatus.PENDING,
                    "expires_at": fire_at + self._ttl,
                }
            )
        return rows

    async def _create_deliveries(self, reminder: Reminder, moments: list[datetime]) -> int:
        if not moments:
            return 0
        user_ids = await self._recipients.list_accepted_user_ids(reminder.id)
        if not user_ids:
            return 0

        occurrences = await self._occurrences.list_for_schedule(reminder.id, moments)
        rows: list[dict[str, Any]] = [
            {
                "occurrence_id": occurrence.id,
                "user_id": user_id,
                "next_attempt_at": occurrence.fire_at,
            }
            for occurrence in occurrences
            for user_id in user_ids
        ]
        return await self._deliveries.insert_missing(rows)
