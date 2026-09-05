"""ops.monitor acceptance criteria (tech.md 24.2, 24.3)."""

from datetime import timedelta

from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

from app.db.repositories.deliveries import DeliveriesRepository
from app.domain.contracts import DeliveryStatus
from app.domain.ops import AlertKind, AlertState
from app.services.ops import MonitorState, OpsService
from tests.conftest import FROZEN_NOW

ADMINS = frozenset({4242, 4243})
ALERT_LAG = timedelta(minutes=5)
WINDOW = timedelta(minutes=15)


def build_service(session, clock, gateway, admins=ADMINS):
    return OpsService(
        session,
        clock,
        gateway,
        admin_ids=admins,
        alert_lag=ALERT_LAG,
        metrics_window=WINDOW,
        lang="en",
    )


async def queue_row(
    reminder_factory,
    occurrence_factory,
    delivery_factory,
    *,
    fire_at=FROZEN_NOW,
    next_attempt_at=None,
    status=DeliveryStatus.PENDING,
):
    reminder = await reminder_factory()
    occurrence = await occurrence_factory(reminder, fire_at=fire_at)
    return await delivery_factory(
        occurrence,
        user_id=reminder.owner_id,
        status=status,
        next_attempt_at=next_attempt_at or fire_at,
    )


# --- the snapshot -----------------------------------------------------------


async def test_the_queue_size_counts_what_is_overdue_not_what_is_planned(
    db_session, reminder_factory, occurrence_factory, delivery_factory
):
    """A reminder due tomorrow is in the queue by design, not by delay."""
    await queue_row(
        reminder_factory,
        occurrence_factory,
        delivery_factory,
        next_attempt_at=FROZEN_NOW - timedelta(minutes=9),
    )
    await queue_row(
        reminder_factory,
        occurrence_factory,
        delivery_factory,
        next_attempt_at=FROZEN_NOW + timedelta(hours=6),
    )
    await db_session.commit()

    snapshot = await DeliveriesRepository(db_session).queue_snapshot(FROZEN_NOW, WINDOW)

    assert snapshot.due_deliveries == 1
    assert snapshot.oldest_due_at == FROZEN_NOW - timedelta(minutes=9)


async def test_the_error_share_ignores_what_is_still_waiting(
    db_session, reminder_factory, occurrence_factory, delivery_factory
):
    """A queued delivery says nothing about transport yet (tech.md 24.2)."""
    for status in (DeliveryStatus.SENT, DeliveryStatus.DONE, DeliveryStatus.FAILED):
        await queue_row(
            reminder_factory,
            occurrence_factory,
            delivery_factory,
            fire_at=FROZEN_NOW - timedelta(minutes=2),
            status=status,
        )
    await queue_row(
        reminder_factory,
        occurrence_factory,
        delivery_factory,
        fire_at=FROZEN_NOW - timedelta(minutes=2),
        status=DeliveryStatus.PENDING,
    )
    await db_session.commit()

    snapshot = await DeliveriesRepository(db_session).queue_snapshot(FROZEN_NOW, WINDOW)

    assert (snapshot.delivered, snapshot.failed) == (2, 1)


async def test_outcomes_older_than_the_window_no_longer_count(
    db_session, reminder_factory, occurrence_factory, delivery_factory
):
    await queue_row(
        reminder_factory,
        occurrence_factory,
        delivery_factory,
        fire_at=FROZEN_NOW - WINDOW - timedelta(minutes=1),
        next_attempt_at=FROZEN_NOW + timedelta(hours=1),
        status=DeliveryStatus.FAILED,
    )
    await db_session.commit()

    snapshot = await DeliveriesRepository(db_session).queue_snapshot(FROZEN_NOW, WINDOW)

    assert (snapshot.delivered, snapshot.failed) == (0, 0)


async def test_an_empty_queue_reads_as_no_lag_and_no_errors(db_session):
    snapshot = await DeliveriesRepository(db_session).queue_snapshot(FROZEN_NOW, WINDOW)

    assert snapshot.due_deliveries == 0
    assert snapshot.oldest_due_at is None
    assert (snapshot.delivered, snapshot.failed) == (0, 0)


# --- the cycle --------------------------------------------------------------


async def test_a_queue_that_keeps_up_alerts_nobody(
    db_session, fake_clock, fake_bot, reminder_factory, occurrence_factory, delivery_factory
):
    await queue_row(
        reminder_factory,
        occurrence_factory,
        delivery_factory,
        next_attempt_at=FROZEN_NOW - timedelta(minutes=1),
    )
    await db_session.commit()
    state = MonitorState()

    result = await build_service(db_session, fake_clock, fake_bot).run(state)

    assert result.notified is None
    assert state.alert is AlertState.CLEAR
    assert fake_bot.sent == []


async def test_running_twice_on_the_same_lag_alerts_once(
    db_session, fake_clock, fake_bot, reminder_factory, occurrence_factory, delivery_factory
):
    """An alert repeated every minute teaches an operator to ignore it."""
    await queue_row(
        reminder_factory,
        occurrence_factory,
        delivery_factory,
        next_attempt_at=FROZEN_NOW - timedelta(minutes=20),
    )
    await db_session.commit()
    service = build_service(db_session, fake_clock, fake_bot)
    state = MonitorState()

    first = await service.run(state)
    second = await service.run(state)

    assert first.notified is AlertKind.RAISED
    assert second.notified is None
    assert len(fake_bot.sent) == len(ADMINS)
    assert {message.chat_id for message in fake_bot.sent} == ADMINS


async def test_catching_up_says_so_once_and_then_falls_silent(
    db_session, fake_clock, fake_bot, reminder_factory, occurrence_factory, delivery_factory
):
    delivery = await queue_row(
        reminder_factory,
        occurrence_factory,
        delivery_factory,
        next_attempt_at=FROZEN_NOW - timedelta(minutes=20),
    )
    await db_session.commit()
    service = build_service(db_session, fake_clock, fake_bot)
    state = MonitorState()
    await service.run(state)

    delivery.status = DeliveryStatus.SENT
    await db_session.commit()
    cleared = await service.run(state)
    again = await service.run(state)

    assert cleared.notified is AlertKind.CLEARED
    assert again.notified is None
    assert state.alert is AlertState.CLEAR
    assert len(fake_bot.sent) == 2 * len(ADMINS)


async def test_the_report_is_published_even_when_nothing_is_alerted(
    db_session, fake_clock, fake_bot, reminder_factory, occurrence_factory, delivery_factory
):
    """/metrics has nothing to show until the cycle leaves it something."""
    await queue_row(
        reminder_factory,
        occurrence_factory,
        delivery_factory,
        next_attempt_at=FROZEN_NOW - timedelta(minutes=3),
    )
    await db_session.commit()
    state = MonitorState()

    await build_service(db_session, fake_clock, fake_bot).run(state)

    assert state.report is not None
    assert state.report.taken_at == FROZEN_NOW
    assert state.report.lag == timedelta(minutes=3)


async def test_a_stand_without_admins_still_measures(
    db_session, fake_clock, fake_bot, reminder_factory, occurrence_factory, delivery_factory
):
    await queue_row(
        reminder_factory,
        occurrence_factory,
        delivery_factory,
        next_attempt_at=FROZEN_NOW - timedelta(minutes=20),
    )
    await db_session.commit()
    state = MonitorState()

    result = await build_service(db_session, fake_clock, fake_bot, admins=frozenset()).run(state)

    assert result.report.lag == timedelta(minutes=20)
    assert state.alert is AlertState.FIRING
    assert fake_bot.sent == []


# --- the error path ---------------------------------------------------------


async def test_a_retry_after_leaves_the_edge_for_the_next_tick(
    db_session, fake_clock, fake_bot, reminder_factory, occurrence_factory, delivery_factory
):
    """Losing the warning would be worse than delivering it a minute late."""
    await queue_row(
        reminder_factory,
        occurrence_factory,
        delivery_factory,
        next_attempt_at=FROZEN_NOW - timedelta(minutes=20),
    )
    await db_session.commit()
    service = build_service(db_session, fake_clock, fake_bot)
    state = MonitorState()
    for _ in ADMINS:
        fake_bot.fail_next(TelegramRetryAfter(method=None, message="flood", retry_after=5))

    blocked_tick = await service.run(state)
    next_tick = await service.run(state)

    assert blocked_tick.notified is None
    assert state.alert is AlertState.FIRING
    assert next_tick.notified is AlertKind.RAISED
    assert len(fake_bot.sent) == len(ADMINS)


async def test_one_unreachable_admin_does_not_cost_the_others_their_warning(
    db_session, fake_clock, fake_bot, reminder_factory, occurrence_factory, delivery_factory
):
    await queue_row(
        reminder_factory,
        occurrence_factory,
        delivery_factory,
        next_attempt_at=FROZEN_NOW - timedelta(minutes=20),
    )
    await db_session.commit()
    state = MonitorState()
    fake_bot.fail_next(TelegramForbiddenError(method=None, message="blocked"))

    result = await build_service(db_session, fake_clock, fake_bot).run(state)

    assert result.notified is AlertKind.RAISED
    assert result.recipients == 1
    assert state.muted_admins == frozenset({min(ADMINS)})


async def test_an_admin_who_blocked_the_bot_is_not_written_to_again(
    db_session, fake_clock, fake_bot, reminder_factory, occurrence_factory, delivery_factory
):
    """The user row is not touched: `is_blocked` belongs to reminder delivery,
    and an admin may have no row at all."""
    delivery = await queue_row(
        reminder_factory,
        occurrence_factory,
        delivery_factory,
        next_attempt_at=FROZEN_NOW - timedelta(minutes=20),
    )
    await db_session.commit()
    service = build_service(db_session, fake_clock, fake_bot)
    state = MonitorState()
    fake_bot.fail_next(TelegramForbiddenError(method=None, message="blocked"))
    await service.run(state)

    delivery.status = DeliveryStatus.SENT
    await db_session.commit()
    await service.run(state)

    assert {message.chat_id for message in fake_bot.sent} == {max(ADMINS)}
