"""reaper.sweep acceptance criteria (tech.md 7.3)."""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

from app.db.models import Delivery, DeliveryAction, FSMState, Occurrence, ReminderRecipient
from app.domain.contracts import ActionKind, DeliveryStatus, OccurrenceStatus, RecipientRole
from app.services.dispatching import ReaperService
from tests.conftest import FROZEN_NOW

#: 23:00 local in Europe/Moscow, an hour into the silence below.
NIGHT = datetime(2026, 6, 1, 20, 0, tzinfo=UTC)

QUIET_NIGHT = {"quiet_start": time(22, 0), "quiet_end": time(7, 0)}


def build_service(session, clock, gateway) -> ReaperService:
    return ReaperService(session, clock, gateway)


@pytest.fixture
async def overdue(db_session, reminder_factory, occurrence_factory, delivery_factory):
    reminder = await reminder_factory()
    occurrence = await occurrence_factory(
        reminder,
        fire_at=FROZEN_NOW - timedelta(hours=5),
        expires_at=FROZEN_NOW - timedelta(hours=2),
        status=OccurrenceStatus.SENT,
    )
    delivery = await delivery_factory(
        occurrence,
        user_id=reminder.owner_id,
        status=DeliveryStatus.SENT,
        sent_at=FROZEN_NOW - timedelta(hours=5),
        tg_message_id=777,
    )
    await db_session.commit()
    return reminder, occurrence, delivery


async def reload(session, model, pk):
    return await session.get(model, pk, populate_existing=True)


async def count_actions(session, delivery_id: int, kind: ActionKind) -> int:
    stmt = sa.select(sa.func.count()).where(
        DeliveryAction.delivery_id == delivery_id, DeliveryAction.kind == kind
    )
    return int((await session.execute(stmt)).scalar_one())


async def test_overdue_occurrence_expires_and_loses_its_buttons(
    db_session, fake_clock, fake_bot, overdue
):
    _, occurrence, delivery = overdue

    result = await build_service(db_session, fake_clock, fake_bot).sweep()

    assert result.expired == 1
    assert (await reload(db_session, Occurrence, occurrence.id)).status is (
        OccurrenceStatus.EXPIRED
    )
    assert await count_actions(db_session, delivery.id, ActionKind.AUTO_EXPIRE) == 1
    assert fake_bot.edited[0][0].message_id == 777
    assert fake_bot.edited[0][2] is None


async def test_sweeping_twice_expires_once(db_session, fake_clock, fake_bot, overdue):
    _, _, delivery = overdue
    service = build_service(db_session, fake_clock, fake_bot)

    await service.sweep()
    second = await service.sweep()

    assert second.expired == 0
    assert await count_actions(db_session, delivery.id, ActionKind.AUTO_EXPIRE) == 1
    assert len(fake_bot.edited) == 1


async def test_unanswered_reminder_is_repeated_once_per_sweep(
    db_session, fake_clock, fake_bot, reminder_factory, occurrence_factory, delivery_factory
):
    reminder = await reminder_factory(repeat_after_minutes=30, max_repeats=2)
    occurrence = await occurrence_factory(
        reminder,
        fire_at=FROZEN_NOW - timedelta(hours=1),
        expires_at=FROZEN_NOW + timedelta(hours=2),
        status=OccurrenceStatus.SENT,
    )
    delivery = await delivery_factory(
        occurrence,
        user_id=reminder.owner_id,
        status=DeliveryStatus.SENT,
        sent_at=FROZEN_NOW - timedelta(hours=1),
    )
    await db_session.commit()
    service = build_service(db_session, fake_clock, fake_bot)

    first = await service.sweep()
    second = await service.sweep()

    assert (first.repeated, second.repeated) == (1, 0)
    stored = await reload(db_session, Delivery, delivery.id)
    assert stored.status is DeliveryStatus.PENDING
    assert stored.next_attempt_at == FROZEN_NOW
    assert (await reload(db_session, Occurrence, occurrence.id)).repeats_sent == 1


async def test_repeat_budget_is_respected(
    db_session, fake_clock, fake_bot, reminder_factory, occurrence_factory, delivery_factory
):
    reminder = await reminder_factory(repeat_after_minutes=30, max_repeats=1)
    occurrence = await occurrence_factory(
        reminder,
        fire_at=FROZEN_NOW - timedelta(hours=1),
        expires_at=FROZEN_NOW + timedelta(hours=2),
        status=OccurrenceStatus.SENT,
        repeats_sent=1,
    )
    await delivery_factory(
        occurrence,
        user_id=reminder.owner_id,
        status=DeliveryStatus.SENT,
        sent_at=FROZEN_NOW - timedelta(hours=1),
    )
    await db_session.commit()

    assert (await build_service(db_session, fake_clock, fake_bot).sweep()).repeated == 0


async def test_stale_lease_is_released(
    db_session, fake_clock, fake_bot, reminder_factory, occurrence_factory, delivery_factory
):
    reminder = await reminder_factory()
    occurrence = await occurrence_factory(reminder)
    delivery = await delivery_factory(
        occurrence, user_id=reminder.owner_id, locked_until=FROZEN_NOW - timedelta(minutes=1)
    )
    await db_session.commit()

    result = await build_service(db_session, fake_clock, fake_bot).sweep()

    assert result.locks_released == 1
    assert (await reload(db_session, Delivery, delivery.id)).locked_until is None


async def test_stale_wizard_state_is_purged(db_session, fake_clock, fake_bot):
    db_session.add(
        FSMState(
            key="stale",
            state="ReminderWizard:title",
            data={},
            updated_at=FROZEN_NOW - timedelta(days=2),
        )
    )
    db_session.add(FSMState(key="fresh", state=None, data={}, updated_at=FROZEN_NOW))
    await db_session.commit()

    result = await build_service(db_session, fake_clock, fake_bot).sweep()

    assert result.fsm_states_purged == 1
    assert await db_session.get(FSMState, "fresh") is not None
    assert await db_session.get(FSMState, "stale") is None


async def test_a_repeat_waits_for_the_end_of_the_quiet_hours(
    db_session,
    fake_clock,
    fake_bot,
    user_factory,
    reminder_factory,
    occurrence_factory,
    delivery_factory,
):
    """A reminder the user did not answer must not come back at midnight."""
    fake_clock.set(NIGHT)
    owner = await user_factory(timezone="Europe/Moscow", **QUIET_NIGHT)
    reminder = await reminder_factory(owner=owner, repeat_after_minutes=30, max_repeats=2)
    occurrence = await occurrence_factory(
        reminder,
        fire_at=NIGHT - timedelta(hours=1),
        expires_at=NIGHT + timedelta(hours=12),
        status=OccurrenceStatus.SENT,
    )
    delivery = await delivery_factory(
        occurrence,
        user_id=owner.id,
        status=DeliveryStatus.SENT,
        sent_at=NIGHT - timedelta(hours=1),
    )
    await db_session.commit()

    assert (await build_service(db_session, fake_clock, fake_bot).sweep()).repeated == 1

    stored = await reload(db_session, Delivery, delivery.id)
    assert stored.next_attempt_at.astimezone(ZoneInfo("Europe/Moscow")) == datetime(
        2026, 6, 2, 7, 0, tzinfo=ZoneInfo("Europe/Moscow")
    )


async def test_a_repeat_the_silence_outlives_is_dropped_rather_than_deferred(
    db_session,
    fake_clock,
    fake_bot,
    user_factory,
    reminder_factory,
    occurrence_factory,
    delivery_factory,
):
    """Its buttons would be dead by the time the silence ends."""
    fake_clock.set(NIGHT)
    owner = await user_factory(timezone="Europe/Moscow", **QUIET_NIGHT)
    reminder = await reminder_factory(owner=owner, repeat_after_minutes=30, max_repeats=2)
    occurrence = await occurrence_factory(
        reminder,
        fire_at=NIGHT - timedelta(hours=1),
        expires_at=NIGHT + timedelta(hours=2),
        status=OccurrenceStatus.SENT,
    )
    delivery = await delivery_factory(
        occurrence,
        user_id=owner.id,
        status=DeliveryStatus.SENT,
        sent_at=NIGHT - timedelta(hours=1),
    )
    await db_session.commit()

    assert (await build_service(db_session, fake_clock, fake_bot).sweep()).repeated == 0

    stored = await reload(db_session, Delivery, delivery.id)
    assert stored.status is DeliveryStatus.SENT
    # The budget is untouched, so the reminder still repeats once it is audible.
    assert (await reload(db_session, Occurrence, occurrence.id)).repeats_sent == 0


async def test_the_repeat_budget_counts_queued_repeats_not_delivered_ones(
    db_session, fake_clock, fake_bot, reminder_factory, occurrence_factory, delivery_factory
):
    """Sweeping twice in a row must not queue a second repeat of the same send."""
    reminder = await reminder_factory(repeat_after_minutes=30, max_repeats=2)
    occurrence = await occurrence_factory(
        reminder,
        fire_at=FROZEN_NOW - timedelta(hours=1),
        expires_at=FROZEN_NOW + timedelta(hours=2),
        status=OccurrenceStatus.SENT,
    )
    await delivery_factory(
        occurrence,
        user_id=reminder.owner_id,
        status=DeliveryStatus.SENT,
        sent_at=FROZEN_NOW - timedelta(hours=1),
    )
    await db_session.commit()
    service = build_service(db_session, fake_clock, fake_bot)

    await service.sweep()
    await service.sweep()

    assert (await reload(db_session, Occurrence, occurrence.id)).repeats_sent == 1


@pytest.mark.parametrize(
    "error",
    [
        TelegramForbiddenError(method=None, message="blocked"),
        TelegramRetryAfter(method=None, message="flood", retry_after=5),
    ],
    ids=["forbidden", "retry_after"],
)
async def test_an_occurrence_expires_even_when_its_message_cannot_be_edited(
    db_session, fake_clock, fake_bot, overdue, error
):
    """Telegram refusing the edit must not leave the queue holding a dead row."""
    _, occurrence, delivery = overdue
    fake_bot.fail_next(error)

    result = await build_service(db_session, fake_clock, fake_bot).sweep()

    assert result.expired == 1
    assert (await reload(db_session, Occurrence, occurrence.id)).status is (
        OccurrenceStatus.EXPIRED
    )
    assert await count_actions(db_session, delivery.id, ActionKind.AUTO_EXPIRE) == 1
    assert fake_bot.edited == []


async def test_an_answered_occurrence_is_never_expired_underneath_the_user(
    db_session, fake_clock, fake_bot, reminder_factory, occurrence_factory, delivery_factory
):
    reminder = await reminder_factory()
    occurrence = await occurrence_factory(
        reminder,
        fire_at=FROZEN_NOW - timedelta(hours=5),
        expires_at=FROZEN_NOW - timedelta(hours=2),
        status=OccurrenceStatus.DONE,
    )
    delivery = await delivery_factory(
        occurrence, user_id=reminder.owner_id, status=DeliveryStatus.DONE
    )
    await db_session.commit()

    result = await build_service(db_session, fake_clock, fake_bot).sweep()

    assert result.expired == 0
    assert (await reload(db_session, Occurrence, occurrence.id)).status is OccurrenceStatus.DONE
    assert await count_actions(db_session, delivery.id, ActionKind.AUTO_EXPIRE) == 0


async def test_one_sweep_costs_one_repeat_however_many_recipients_it_reaches(
    db_session,
    fake_clock,
    fake_bot,
    user_factory,
    reminder_factory,
    occurrence_factory,
    delivery_factory,
):
    """The budget lives on the occurrence, not on a delivery (tech.md 4.2)."""
    reminder = await reminder_factory(repeat_after_minutes=30, max_repeats=1)
    watcher = await user_factory()
    db_session.add(
        ReminderRecipient(
            reminder_id=reminder.id,
            user_id=watcher.id,
            role=RecipientRole.WATCHER,
            accepted_at=FROZEN_NOW,
        )
    )
    occurrence = await occurrence_factory(
        reminder,
        fire_at=FROZEN_NOW - timedelta(hours=1),
        expires_at=FROZEN_NOW + timedelta(hours=2),
        status=OccurrenceStatus.SENT,
    )
    for user_id in (reminder.owner_id, watcher.id):
        await delivery_factory(
            occurrence,
            user_id=user_id,
            status=DeliveryStatus.SENT,
            sent_at=FROZEN_NOW - timedelta(hours=1),
        )
    await db_session.commit()

    result = await build_service(db_session, fake_clock, fake_bot).sweep()

    assert result.repeated == 2, "both recipients are reminded again"
    assert (await reload(db_session, Occurrence, occurrence.id)).repeats_sent == 1
