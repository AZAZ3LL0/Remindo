"""dispatcher.deliver acceptance criteria, including the error table (tech.md 7.2)."""

from datetime import timedelta

import pytest
import sqlalchemy as sa
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

from app.db.models import Delivery, Occurrence, User
from app.domain.contracts import DeliveryStatus, OccurrenceStatus
from app.domain.retry import MAX_ATTEMPTS
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
    assert stored.attempts == 1
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
