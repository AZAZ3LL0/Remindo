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
from app.domain.quiet_hours import apply_quiet_hours
from app.domain.recurrence import next_occurrences
from app.domain.schedules import parse_schedule

#: Upper bound on occurrences materialised for one reminder in one cycle.
MAX_OCCURRENCES_PER_CYCLE = 500

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

        # `after` is exclusive, so the very first moment at starts_at survives.
        after = reminder.planned_until or reminder.starts_at - timedelta(microseconds=1)
        until = min(horizon_end, reminder.ends_at) if reminder.ends_at else horizon_end
        limit = MAX_OCCURRENCES_PER_CYCLE
        if reminder.max_occurrences is not None:
            limit = min(limit, max(reminder.max_occurrences - reminder.fired_count, 0))

        moments = (
            next_occurrences(schedule, tz, after=after, until=until, limit=limit)
            if limit and until > after
            else []
        )

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

        created_occurrences = await self._occurrences.insert_missing(rows)
        created_deliveries = await self._create_deliveries(reminder, moments)

        fired_count = await self._occurrences.count_for_reminder(reminder.id)
        await self._reminders.set_planning_state(reminder.id, until, fired_count)

        archived = 0
        if self._is_exhausted(reminder, fired_count, until):
            await self._reminders.set_status(reminder.id, ReminderStatus.ARCHIVED)
            archived = 1

        return created_occurrences, created_deliveries, archived

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

    @staticmethod
    def _is_exhausted(reminder: Reminder, fired_count: int, planned_until: datetime) -> bool:
        if reminder.max_occurrences is not None and fired_count >= reminder.max_occurrences:
            return True
        return reminder.ends_at is not None and planned_until >= reminder.ends_at
