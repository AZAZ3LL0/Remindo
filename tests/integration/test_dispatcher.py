"""dispatcher.deliver acceptance criteria, including the error table (tech.md 7.2)."""

import asyncio
from datetime import timedelta

import pytest
import sqlalchemy as sa
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import Category, Delivery, Occurrence, Reminder, User
from app.db.repositories.deliveries import DeliveriesRepository
from app.domain.contracts import (
    DeliveryStatus,
    OccurrenceStatus,
    ReminderStatus,
    ScheduleKind,
)
from app.domain.retry import MAX_ATTEMPTS
from app.domain.schedules import IntervalSchedule, dump_schedule
from app.services.dispatching import DispatchingService
from tests.conftest import FROZEN_NOW


def build_service(session, clock, gateway) -> DispatchingService:
    return DispatchingService(session, clock, gateway, batch_size=100, lock_seconds=60)


@pytest.fixture
async def due(db_session, reminder_factory, occurrence_factory, delivery_factory):
    reminder = await reminder_factory()
    occurrence = await occurrence_factory(reminder, fire_at=FROZEN_NOW - timedelta(minutes=1))
    delivery = await delivery_factory(occurrence, user_id=reminder.owner_id)
    await db_session.commit()
    return reminder, occurrence, delivery


async def reload(session, model, pk):
    return await session.get(model, pk, populate_existing=True)


async def test_due_delivery_is_sent_and_marked(db_session, fake_clock, fake_bot, due):
    _, occurrence, delivery = due

    result = await build_service(db_session, fake_clock, fake_bot).deliver()

    assert (result.claimed, result.sent) == (1, 1)
    assert len(fake_bot.sent) == 1

    stored = await reload(db_session, Delivery, delivery.id)
    assert stored.status is DeliveryStatus.SENT
    assert stored.sent_at == FROZEN_NOW
    assert stored.tg_message_id is not None
    assert stored.locked_until is None
    assert (await reload(db_session, Occurrence, occurrence.id)).status is OccurrenceStatus.SENT


async def test_running_the_cycle_twice_sends_one_message(db_session, fake_clock, fake_bot, due):
    service = build_service(db_session, fake_clock, fake_bot)

    await service.deliver()
    second = await service.deliver()

    assert second.claimed == 0
    assert len(fake_bot.sent) == 1


async def test_a_future_delivery_is_not_claimed(
    db_session, fake_clock, fake_bot, reminder_factory, occurrence_factory, delivery_factory
):
    reminder = await reminder_factory()
    occurrence = await occurrence_factory(reminder, fire_at=FROZEN_NOW + timedelta(hours=1))
    await delivery_factory(occurrence, user_id=reminder.owner_id)
    await db_session.commit()

    assert (await build_service(db_session, fake_clock, fake_bot).deliver()).claimed == 0
    assert fake_bot.sent == []


async def test_retry_after_reschedules_without_losing_the_message(
    db_session, fake_clock, fake_bot, due
):
    _, _, delivery = due
    fake_bot.fail_next(TelegramRetryAfter(method=None, message="flood", retry_after=5))

    result = await build_service(db_session, fake_clock, fake_bot).deliver()

    stored = await reload(db_session, Delivery, delivery.id)
    assert result.retried == 1
    assert stored.status is DeliveryStatus.PENDING
    assert stored.next_attempt_at == FROZEN_NOW + timedelta(seconds=6)
    # Flood control is not this delivery's fault, so it keeps its budget.
    assert stored.attempts == 0
    assert stored.locked_until is None


async def test_blocked_bot_stops_retrying_and_marks_the_user(db_session, fake_clock, fake_bot, due):
    _, _, delivery = due
    fake_bot.fail_next(TelegramForbiddenError(method=None, message="bot was blocked"))

    result = await build_service(db_session, fake_clock, fake_bot).deliver()

    stored = await reload(db_session, Delivery, delivery.id)
    assert result.blocked == 1
    assert stored.status is DeliveryStatus.BLOCKED
    assert (await reload(db_session, User, delivery.user_id)).is_blocked is True


async def test_bad_request_fails_without_retry(db_session, fake_clock, fake_bot, due):
    _, _, delivery = due
    fake_bot.fail_next(TelegramBadRequest(method=None, message="bad payload"))

    result = await build_service(db_session, fake_clock, fake_bot).deliver()

    stored = await reload(db_session, Delivery, delivery.id)
    assert result.failed == 1
    assert stored.status is DeliveryStatus.FAILED
    assert stored.error_code == "TelegramBadRequest"


async def test_timeout_backs_off_exponentially(db_session, fake_clock, fake_bot, due):
    _, _, delivery = due
    fake_bot.fail_next(TimeoutError())

    await build_service(db_session, fake_clock, fake_bot).deliver()

    stored = await reload(db_session, Delivery, delivery.id)
    assert stored.status is DeliveryStatus.PENDING
    assert stored.next_attempt_at == FROZEN_NOW + timedelta(seconds=30)


async def test_delivery_fails_after_the_attempt_budget(db_session, fake_clock, fake_bot, due):
    _, _, delivery = due
    await db_session.execute(
        sa.update(Delivery).where(Delivery.id == delivery.id).values(attempts=MAX_ATTEMPTS - 1)
    )
    await db_session.commit()
    fake_bot.fail_next(TimeoutError())

    result = await build_service(db_session, fake_clock, fake_bot).deliver()

    stored = await reload(db_session, Delivery, delivery.id)
    assert result.failed == 1
    assert stored.status is DeliveryStatus.FAILED
    assert stored.attempts == MAX_ATTEMPTS


async def test_claim_takes_a_lease_before_sending(db_session, fake_clock, fake_bot, due):
    """The lease is what keeps a second worker off the same row."""
    _, _, delivery = due
    fake_bot.fail_next(TimeoutError())

    await build_service(db_session, fake_clock, fake_bot).deliver()

    stored = await reload(db_session, Delivery, delivery.id)
    assert stored.attempts == 1
    assert stored.error_code == "TimeoutError"


async def test_a_snoozed_delivery_comes_back_when_it_is_due(db_session, fake_clock, fake_bot, due):
    """A snooze postpones the message, it does not drop it (tech.md 7.4)."""
    _, _, delivery = due
    await db_session.execute(
        sa.update(Delivery)
        .where(Delivery.id == delivery.id)
        .values(
            status=DeliveryStatus.SNOOZED,
            snoozed_until=FROZEN_NOW - timedelta(seconds=1),
            next_attempt_at=FROZEN_NOW - timedelta(seconds=1),
        )
    )
    await db_session.commit()

    result = await build_service(db_session, fake_clock, fake_bot).deliver()

    assert (result.claimed, result.sent) == (1, 1)
    assert (await reload(db_session, Delivery, delivery.id)).status is DeliveryStatus.SENT


async def test_a_closed_occurrence_is_not_delivered(db_session, fake_clock, fake_bot, due):
    """The reaper already took the buttons away; a message would be a dead end."""
    _, occurrence, delivery = due
    await db_session.execute(
        sa.update(Occurrence)
        .where(Occurrence.id == occurrence.id)
        .values(status=OccurrenceStatus.EXPIRED)
    )
    await db_session.commit()

    result = await build_service(db_session, fake_clock, fake_bot).deliver()

    assert (result.claimed, result.failed) == (1, 1)
    assert fake_bot.sent == []
    stored = await reload(db_session, Delivery, delivery.id)
    assert stored.status is DeliveryStatus.FAILED
    assert stored.error_code == "occurrence_closed"
    assert stored.attempts == 0


async def test_a_blocked_user_is_not_called_again(db_session, fake_clock, fake_bot, due):
    """Telegram already said no; calling again only burns the flood budget."""
    _, _, delivery = due
    await db_session.execute(
        sa.update(User).where(User.id == delivery.user_id).values(is_blocked=True)
    )
    await db_session.commit()

    result = await build_service(db_session, fake_clock, fake_bot).deliver()

    assert result.blocked == 1
    assert fake_bot.sent == []
    stored = await reload(db_session, Delivery, delivery.id)
    assert stored.status is DeliveryStatus.BLOCKED
    assert stored.error_code == "user_blocked"


async def test_a_delivered_message_clears_the_attempt_budget(db_session, fake_clock, fake_bot, due):
    """Otherwise repeats and snoozes would exhaust the budget of a healthy row."""
    _, _, delivery = due
    await db_session.execute(
        sa.update(Delivery).where(Delivery.id == delivery.id).values(attempts=MAX_ATTEMPTS - 1)
    )
    await db_session.commit()

    await build_service(db_session, fake_clock, fake_bot).deliver()

    assert (await reload(db_session, Delivery, delivery.id)).attempts == 0


async def test_a_retry_is_delivered_once_it_becomes_due(db_session, fake_clock, fake_bot, due):
    _, _, delivery = due
    fake_bot.fail_next(TimeoutError())
    service = build_service(db_session, fake_clock, fake_bot)

    await service.deliver()
    too_early = await service.deliver()
    assert (too_early.claimed, fake_bot.sent) == (0, [])

    fake_clock.advance(timedelta(seconds=31))
    later = await service.deliver()

    assert (later.claimed, later.sent) == (1, 1)
    assert len(fake_bot.sent) == 1
    stored = await reload(db_session, Delivery, delivery.id)
    assert stored.status is DeliveryStatus.SENT
    assert stored.attempts == 0


async def test_the_batch_takes_the_oldest_due_deliveries_first(
    db_session, fake_clock, fake_bot, reminder_factory, occurrence_factory, delivery_factory
):
    """A backlog drains in queue order, never at random."""
    reminder = await reminder_factory()
    queue = {}
    for minutes in (30, 10, 20):
        occurrence = await occurrence_factory(
            reminder, fire_at=FROZEN_NOW - timedelta(minutes=minutes)
        )
        queue[minutes] = await delivery_factory(occurrence, user_id=reminder.owner_id)
    await db_session.commit()

    service = DispatchingService(db_session, fake_clock, fake_bot, batch_size=2, lock_seconds=60)
    result = await service.deliver()

    assert (result.claimed, result.sent) == (2, 2)
    statuses = {
        minutes: (await reload(db_session, Delivery, delivery.id)).status
        for minutes, delivery in queue.items()
    }
    assert statuses == {
        30: DeliveryStatus.SENT,
        20: DeliveryStatus.SENT,
        10: DeliveryStatus.PENDING,
    }


async def test_a_lease_hides_a_claimed_delivery_from_the_next_claim(db_session, fake_clock, due):
    """The lease, not the status, is what protects a row during the send."""
    repository = DeliveriesRepository(db_session)
    lease = timedelta(seconds=60)

    first = await repository.claim_due(FROZEN_NOW, lease, batch=10)
    second = await repository.claim_due(FROZEN_NOW, lease, batch=10)

    assert len(first) == 1
    assert second == []
    assert first[0].attempts == 1


async def test_an_expired_lease_is_claimed_again(db_session, fake_clock, due):
    """At-least-once: a worker that died mid-send must not strand the row."""
    repository = DeliveriesRepository(db_session)
    lease = timedelta(seconds=60)

    await repository.claim_due(FROZEN_NOW, lease, batch=10)
    reclaimed = await repository.claim_due(FROZEN_NOW + timedelta(seconds=61), lease, batch=10)

    assert len(reclaimed) == 1
    assert reclaimed[0].attempts == 2


#: Reserved for the race below, which owns its rows instead of borrowing the
#: rolled-back transaction every other test runs in.
RACE_TG_ID = 999_000_001
RACE_CATEGORY_CODE = "race_probe"


async def _purge_race_rows(factory) -> None:
    """Cascades from users clear the queue; the category has no owner to follow."""
    async with factory() as session:
        await session.execute(sa.delete(User).where(User.tg_user_id == RACE_TG_ID))
        await session.execute(sa.delete(Category).where(Category.code == RACE_CATEGORY_CODE))
        await session.commit()


async def _seed_one_due_delivery(factory) -> None:
    async with factory() as session:
        user = User(tg_user_id=RACE_TG_ID, tg_chat_id=RACE_TG_ID, first_name="Race")
        category = Category(code=RACE_CATEGORY_CODE, title="Race", emoji="💧", is_system=True)
        session.add_all([user, category])
        await session.flush()
        reminder = Reminder(
            owner_id=user.id,
            category_id=category.id,
            title="Пить воду",
            status=ReminderStatus.ACTIVE,
            schedule_kind=ScheduleKind.INTERVAL,
            schedule=dump_schedule(
                IntervalSchedule(every_minutes=120, window_start="09:00", window_end="21:00")
            ),
            timezone=user.timezone,
            starts_at=FROZEN_NOW - timedelta(hours=1),
        )
        session.add(reminder)
        await session.flush()
        occurrence = Occurrence(
            reminder_id=reminder.id,
            scheduled_for=FROZEN_NOW - timedelta(minutes=1),
            fire_at=FROZEN_NOW - timedelta(minutes=1),
            expires_at=FROZEN_NOW + timedelta(hours=3),
        )
        session.add(occurrence)
        await session.flush()
        session.add(
            Delivery(
                occurrence_id=occurrence.id,
                user_id=user.id,
                next_attempt_at=FROZEN_NOW - timedelta(minutes=1),
            )
        )
        await session.commit()


async def test_two_workers_never_claim_the_same_delivery(engine, fake_clock, fake_bot):
    """SKIP LOCKED is the whole reason the queue needs no broker (tech.md 7.2).

    Two connections have to see the same committed row, so this test owns its
    data instead of borrowing the transaction the other tests roll back.
    """
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    await _purge_race_rows(factory)
    await _seed_one_due_delivery(factory)

    try:
        async with factory() as first, factory() as second:
            results = await asyncio.gather(
                build_service(first, fake_clock, fake_bot).deliver(),
                build_service(second, fake_clock, fake_bot).deliver(),
            )

        assert sum(result.claimed for result in results) == 1
        assert sum(result.sent for result in results) == 1
        assert len(fake_bot.sent) == 1
    finally:
        await _purge_race_rows(factory)


async def test_a_locked_row_is_skipped_instead_of_waited_for(engine, fake_clock):
    """A busy row must not stall the rest of the batch.

    The holder keeps its claim uncommitted, exactly like a worker in the middle
    of a send. Without SKIP LOCKED the rival would sit on the row lock until the
    holder finished, and the timeout below is what turns that stall into a
    failed test instead of a hung suite.
    """
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    await _purge_race_rows(factory)
    await _seed_one_due_delivery(factory)
    lease = timedelta(seconds=60)

    try:
        async with factory() as holder, factory() as rival:
            held = await DeliveriesRepository(holder).claim_due(FROZEN_NOW, lease, batch=10)
            rival_claim = await asyncio.wait_for(
                DeliveriesRepository(rival).claim_due(FROZEN_NOW, lease, batch=10), timeout=5
            )

            assert len(held) == 1
            assert rival_claim == []
            await holder.rollback()
    finally:
        await _purge_race_rows(factory)
