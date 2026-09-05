"""planner.materialize acceptance criteria (tech.md 7.1)."""

from datetime import UTC, datetime, time, timedelta
from itertools import pairwise

import pytest
import sqlalchemy as sa
from pydantic import ValidationError as PydanticValidationError

from app.db.models import Delivery, Occurrence, Reminder
from app.domain.contracts import ReminderStatus
from app.domain.planning import MAX_OCCURRENCES_PER_CYCLE
from app.domain.schedules import (
    DailySchedule,
    IntervalSchedule,
    MonthlySchedule,
    OnceSchedule,
    WeeklySchedule,
    dump_schedule,
)
from app.services.planning import PlanningService
from tests.conftest import FROZEN_NOW


def build_service(session, clock, horizon_hours: int = 48) -> PlanningService:
    return PlanningService(session, clock, horizon_hours=horizon_hours, occurrence_ttl_minutes=180)


async def count(session, model, **filters) -> int:
    stmt = sa.select(sa.func.count()).select_from(model)
    for column, value in filters.items():
        stmt = stmt.where(getattr(model, column) == value)
    return int((await session.execute(stmt)).scalar_one())


async def test_materialize_creates_occurrences_and_deliveries(
    db_session, fake_clock, reminder_factory
):
    reminder = await reminder_factory(
        schedule=DailySchedule(times=["08:00", "20:00"], every_n_days=1)
    )

    result = await build_service(db_session, fake_clock).materialize()

    assert result.reminders_processed == 1
    assert result.occurrences_created == await count(
        db_session, Occurrence, reminder_id=reminder.id
    )
    assert result.deliveries_created == result.occurrences_created


async def test_running_the_cycle_twice_has_one_effect(db_session, fake_clock, reminder_factory):
    reminder = await reminder_factory()
    service = build_service(db_session, fake_clock)

    first = await service.materialize()
    occurrences_after_first = await count(db_session, Occurrence, reminder_id=reminder.id)
    deliveries_after_first = await count(db_session, Delivery)

    second = await service.materialize()

    assert first.occurrences_created > 0
    assert second.occurrences_created == 0
    assert second.deliveries_created == 0
    assert await count(db_session, Occurrence, reminder_id=reminder.id) == occurrences_after_first
    assert await count(db_session, Delivery) == deliveries_after_first


async def test_replanning_the_same_window_creates_no_duplicates(
    db_session, fake_clock, reminder_factory
):
    """Even a forced replan hits the (reminder_id, scheduled_for) unique key."""
    reminder = await reminder_factory()
    service = build_service(db_session, fake_clock)
    await service.materialize()
    expected = await count(db_session, Occurrence, reminder_id=reminder.id)

    await db_session.execute(
        sa.update(Reminder).where(Reminder.id == reminder.id).values(planned_until=None)
    )
    await db_session.commit()
    result = await service.materialize()

    assert result.occurrences_created == 0
    assert await count(db_session, Occurrence, reminder_id=reminder.id) == expected


async def test_nothing_is_materialised_before_the_start(db_session, fake_clock, reminder_factory):
    reminder = await reminder_factory(starts_at=FROZEN_NOW + timedelta(days=10))

    await build_service(db_session, fake_clock).materialize()

    assert await count(db_session, Occurrence, reminder_id=reminder.id) == 0


async def test_end_date_bounds_the_horizon_and_archives(db_session, fake_clock, reminder_factory):
    reminder = await reminder_factory(
        schedule=DailySchedule(times=["08:00"]),
        ends_at=FROZEN_NOW + timedelta(days=1),
    )

    result = await build_service(db_session, fake_clock).materialize()
    await db_session.refresh(reminder)

    fire_times = (
        (
            await db_session.execute(
                sa.select(Occurrence.scheduled_for).where(Occurrence.reminder_id == reminder.id)
            )
        )
        .scalars()
        .all()
    )

    assert all(moment <= reminder.ends_at for moment in fire_times)
    assert result.reminders_archived == 1
    assert reminder.status is ReminderStatus.ARCHIVED


async def test_occurrence_budget_archives_the_reminder(db_session, fake_clock, reminder_factory):
    reminder = await reminder_factory(
        schedule=DailySchedule(times=["08:00", "12:00", "20:00"]), max_occurrences=2
    )

    await build_service(db_session, fake_clock).materialize()
    await db_session.refresh(reminder)

    assert await count(db_session, Occurrence, reminder_id=reminder.id) == 2
    assert reminder.status is ReminderStatus.ARCHIVED


async def test_quiet_hours_move_the_delivery_moment(
    db_session, fake_clock, user_factory, reminder_factory
):
    owner = await user_factory(
        timezone="Europe/Moscow", quiet_start=time(23, 0), quiet_end=time(7, 0)
    )
    reminder = await reminder_factory(
        owner=owner, schedule=DailySchedule(times=["03:00"]), starts_at=FROZEN_NOW
    )

    await build_service(db_session, fake_clock).materialize()

    occurrence = (
        (
            await db_session.execute(
                sa.select(Occurrence).where(Occurrence.reminder_id == reminder.id)
            )
        )
        .scalars()
        .first()
    )
    assert occurrence is not None
    assert occurrence.fire_at > occurrence.scheduled_for
    assert occurrence.expires_at == occurrence.fire_at + timedelta(minutes=180)


async def test_one_shot_reminder_produces_a_single_occurrence(
    db_session, fake_clock, reminder_factory
):
    moment = (FROZEN_NOW + timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M")
    reminder = await reminder_factory(schedule=OnceSchedule(at=moment), timezone="UTC")

    await build_service(db_session, fake_clock).materialize()

    assert await count(db_session, Occurrence, reminder_id=reminder.id) == 1


async def scheduled_moments(session, reminder_id: int) -> list:
    stmt = (
        sa.select(Occurrence.scheduled_for)
        .where(Occurrence.reminder_id == reminder_id)
        .order_by(Occurrence.scheduled_for)
    )
    return list((await session.execute(stmt)).scalars().all())


async def test_the_horizon_bounds_what_a_cycle_materialises(
    db_session, fake_clock, reminder_factory
):
    reminder = await reminder_factory(schedule=DailySchedule(times=["08:00"]), timezone="UTC")

    await build_service(db_session, fake_clock, horizon_hours=48).materialize()
    await db_session.refresh(reminder)

    horizon_end = FROZEN_NOW + timedelta(hours=48)
    assert reminder.planned_until == horizon_end
    assert all(moment <= horizon_end for moment in await scheduled_moments(db_session, reminder.id))


async def test_a_truncated_cycle_resumes_where_it_stopped(db_session, fake_clock, reminder_factory):
    """A schedule denser than one batch keeps every moment, one cycle later."""
    reminder = await reminder_factory(
        schedule=IntervalSchedule(every_minutes=5, window_start="00:00", window_end="23:55"),
        timezone="UTC",
    )
    service = build_service(db_session, fake_clock)

    first = await service.materialize()
    await db_session.refresh(reminder)
    stopped_at = reminder.planned_until

    second = await service.materialize()
    moments = await scheduled_moments(db_session, reminder.id)

    assert first.occurrences_created == MAX_OCCURRENCES_PER_CYCLE
    assert stopped_at == moments[MAX_OCCURRENCES_PER_CYCLE - 1]
    assert second.occurrences_created > 0
    assert len(set(moments)) == len(moments)
    # No gap opened at the seam between the two cycles.
    assert all(later - earlier == timedelta(minutes=5) for earlier, later in pairwise(moments))


async def test_a_spent_one_shot_reminder_is_archived_once(db_session, fake_clock, reminder_factory):
    """A minute already gone is never materialised, so the reminder is over."""
    moment = (FROZEN_NOW - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M")
    reminder = await reminder_factory(schedule=OnceSchedule(at=moment), timezone="UTC")
    service = build_service(db_session, fake_clock)

    first = await service.materialize()
    second = await service.materialize()
    await db_session.refresh(reminder)

    assert first.reminders_archived == 1
    assert second.reminders_processed == 0
    assert second.reminders_archived == 0
    assert await count(db_session, Occurrence, reminder_id=reminder.id) == 0
    assert reminder.status is ReminderStatus.ARCHIVED


async def test_archiving_keeps_what_was_already_planned(db_session, fake_clock, reminder_factory):
    """Archiving stops the planner, it does not cancel a pending delivery."""
    moment = (FROZEN_NOW + timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M")
    reminder = await reminder_factory(schedule=OnceSchedule(at=moment), timezone="UTC")

    await build_service(db_session, fake_clock).materialize()
    await db_session.refresh(reminder)

    assert reminder.status is ReminderStatus.ARCHIVED
    assert await count(db_session, Occurrence, reminder_id=reminder.id) == 1
    assert await count(db_session, Delivery) == 1


async def test_the_budget_is_counted_across_cycles(db_session, fake_clock, reminder_factory):
    reminder = await reminder_factory(
        schedule=DailySchedule(times=["08:00"]), max_occurrences=3, timezone="UTC"
    )
    service = build_service(db_session, fake_clock, horizon_hours=24)

    await service.materialize()
    fake_clock.advance(timedelta(days=1))
    await service.materialize()
    fake_clock.advance(timedelta(days=1))
    await service.materialize()
    await db_session.refresh(reminder)

    assert await count(db_session, Occurrence, reminder_id=reminder.id) == 3
    assert reminder.fired_count == 3
    assert reminder.status is ReminderStatus.ARCHIVED


async def test_the_least_planned_reminder_goes_first(db_session, fake_clock, reminder_factory):
    """A batch smaller than the backlog cannot starve the same reminder twice."""
    ahead = await reminder_factory(planned_until=FROZEN_NOW + timedelta(hours=24))
    waiting = await reminder_factory()
    service = build_service(db_session, fake_clock)
    service._batch_size = 1

    await service.materialize()

    assert await count(db_session, Occurrence, reminder_id=waiting.id) > 0
    assert await count(db_session, Occurrence, reminder_id=ahead.id) == 0


async def test_a_failed_cycle_leaves_no_partial_state(db_session, fake_clock, reminder_factory):
    """The cycle is one transaction: a broken schedule costs the batch, not consistency."""
    healthy_id = (await reminder_factory(schedule=DailySchedule(times=["08:00"]))).id
    broken_id = (await reminder_factory(schedule=DailySchedule(times=["09:00"]))).id
    await db_session.execute(
        sa.update(Reminder)
        .where(Reminder.id == broken_id)
        .values(schedule={"kind": "daily", "times": [], "every_n_days": 1})
    )
    await db_session.commit()
    service = build_service(db_session, fake_clock)

    with pytest.raises(PydanticValidationError):
        await service.materialize()
    await db_session.rollback()

    assert await count(db_session, Occurrence) == 0
    assert await count(db_session, Delivery) == 0

    await db_session.execute(
        sa.update(Reminder)
        .where(Reminder.id == broken_id)
        .values(schedule=dump_schedule(DailySchedule(times=["09:00"])))
    )
    await db_session.commit()
    result = await service.materialize()

    assert result.reminders_processed == 2
    assert await count(db_session, Occurrence, reminder_id=healthy_id) > 0
    assert await count(db_session, Occurrence, reminder_id=broken_id) > 0


@pytest.mark.parametrize(
    "schedule",
    [
        WeeklySchedule(times=["07:30"], weekdays=[1, 3, 5]),
        MonthlySchedule(times=["10:00"], days=[1, 31], on_missing_day="last_day"),
        MonthlySchedule(times=["10:00"], days=[31], on_missing_day="skip"),
        IntervalSchedule(every_minutes=30, window_start="00:00", window_end="00:00"),
    ],
    ids=["weekly", "monthly_last_day", "monthly_skip", "interval_all_day"],
)
async def test_the_new_kinds_survive_a_cycle_run_twice_across_a_transition(
    db_session, fake_clock, reminder_factory, freeze_at, schedule
):
    """Idempotency where it is hardest: a day the local clock is not 24h long.

    A schedule near a transition can produce the same wall-clock time twice, and
    `(reminder_id, scheduled_for)` is the only thing standing between that and a
    doubled queue.
    """
    # Europe/Berlin turns its clocks back on 2026-10-25.
    freeze_at(datetime(2026, 10, 24, 12, 0, tzinfo=UTC))
    reminder = await reminder_factory(schedule=schedule, timezone="Europe/Berlin")
    await db_session.execute(
        sa.update(Reminder)
        .where(Reminder.id == reminder.id)
        .values(starts_at=datetime(2026, 10, 24, 12, 0, tzinfo=UTC), planned_until=None)
    )
    await db_session.commit()
    service = build_service(db_session, fake_clock, horizon_hours=24 * 45)

    first = await service.materialize()
    await db_session.execute(
        sa.update(Reminder).where(Reminder.id == reminder.id).values(planned_until=None)
    )
    await db_session.commit()
    second = await service.materialize()

    moments = (
        (
            await db_session.execute(
                sa.select(Occurrence.scheduled_for).where(Occurrence.reminder_id == reminder.id)
            )
        )
        .scalars()
        .all()
    )

    assert first.occurrences_created > 0
    assert second.occurrences_created == 0
    assert len(set(moments)) == len(moments)
    assert len(moments) == first.occurrences_created
