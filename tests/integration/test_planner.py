"""planner.materialize acceptance criteria (tech.md 7.1)."""

from datetime import time, timedelta

import sqlalchemy as sa

from app.db.models import Delivery, Occurrence, Reminder
from app.domain.contracts import ReminderStatus
from app.domain.schedules import DailySchedule, OnceSchedule
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
