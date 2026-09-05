"""Reaction acceptance criteria (tech.md 7.4)."""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa

from app.db.models import Delivery, DeliveryAction, Occurrence
from app.domain.contracts import ActionKind, DeliveryStatus, OccurrenceStatus
from app.domain.errors import NotFoundError, PermissionDeniedError
from app.domain.reactions import RejectReason
from app.services.reactions import ReactionsService
from tests.conftest import FROZEN_NOW


@pytest.fixture
async def sent(db_session, reminder_factory, occurrence_factory, delivery_factory):
    reminder = await reminder_factory(snooze_minutes=15)
    occurrence = await occurrence_factory(reminder, fire_at=FROZEN_NOW - timedelta(minutes=5))
    delivery = await delivery_factory(
        occurrence,
        user_id=reminder.owner_id,
        status=DeliveryStatus.SENT,
        sent_at=FROZEN_NOW - timedelta(minutes=5),
        tg_message_id=555,
    )
    await db_session.commit()
    return reminder, occurrence, delivery


async def count_actions(session, delivery_id: int, kind: ActionKind | None = None) -> int:
    stmt = sa.select(sa.func.count()).where(DeliveryAction.delivery_id == delivery_id)
    if kind is not None:
        stmt = stmt.where(DeliveryAction.kind == kind)
    return int((await session.execute(stmt)).scalar_one())


async def reload(session, model, pk):
    return await session.get(model, pk, populate_existing=True)


@pytest.mark.parametrize(
    ("action", "status", "kind"),
    [
        ("done", DeliveryStatus.DONE, ActionKind.DONE),
        ("skip", DeliveryStatus.SKIPPED, ActionKind.SKIP),
        ("snooze", DeliveryStatus.SNOOZED, ActionKind.SNOOZE),
    ],
)
async def test_reacting_twice_has_one_effect(db_session, fake_clock, sent, action, status, kind):
    _, _, delivery = sent
    service = ReactionsService(db_session, fake_clock)

    first = await service.react(delivery.id, delivery.user_id, action)
    second = await service.react(delivery.id, delivery.user_id, action)

    assert first.applied is True
    assert second.applied is False
    assert second.reason is RejectReason.ALREADY_HANDLED
    assert (await reload(db_session, Delivery, delivery.id)).status is status
    assert await count_actions(db_session, delivery.id, kind) == 1


async def test_done_marks_the_occurrence_when_every_recipient_answered(
    db_session, fake_clock, sent
):
    _, occurrence, delivery = sent

    await ReactionsService(db_session, fake_clock).react(delivery.id, delivery.user_id, "done")

    stored = await reload(db_session, Occurrence, occurrence.id)
    assert stored.status is OccurrenceStatus.DONE


async def test_occurrence_waits_for_the_second_recipient(
    db_session, fake_clock, sent, user_factory, delivery_factory
):
    _, occurrence, delivery = sent
    watcher = await user_factory()
    await delivery_factory(occurrence, user_id=watcher.id, status=DeliveryStatus.SENT)
    await db_session.commit()

    await ReactionsService(db_session, fake_clock).react(delivery.id, delivery.user_id, "done")

    stored = await reload(db_session, Occurrence, occurrence.id)
    assert stored.status is not OccurrenceStatus.DONE


async def test_snooze_moves_the_next_attempt(db_session, fake_clock, sent):
    reminder, _, delivery = sent

    result = await ReactionsService(db_session, fake_clock).react(
        delivery.id, delivery.user_id, "snooze"
    )

    stored = await reload(db_session, Delivery, delivery.id)
    expected = FROZEN_NOW + timedelta(minutes=reminder.snooze_minutes)
    assert result.snoozed_until == expected
    assert stored.next_attempt_at == expected
    assert stored.snoozed_until == expected


async def test_expired_occurrence_rejects_the_reaction(db_session, fake_clock, sent):
    _, occurrence, delivery = sent
    await db_session.execute(
        sa.update(Occurrence)
        .where(Occurrence.id == occurrence.id)
        .values(expires_at=FROZEN_NOW - timedelta(minutes=1))
    )
    await db_session.commit()

    result = await ReactionsService(db_session, fake_clock).react(
        delivery.id, delivery.user_id, "done"
    )

    assert result.applied is False
    assert result.reason is RejectReason.EXPIRED
    assert await count_actions(db_session, delivery.id) == 0


async def test_another_user_may_not_react(db_session, fake_clock, sent, user_factory):
    _, _, delivery = sent
    stranger = await user_factory()
    await db_session.commit()

    with pytest.raises(PermissionDeniedError):
        await ReactionsService(db_session, fake_clock).react(delivery.id, stranger.id, "done")


async def test_unknown_delivery_is_reported(db_session, fake_clock):
    with pytest.raises(NotFoundError):
        await ReactionsService(db_session, fake_clock).react(10**9, 1, "done")


async def test_snoozing_twice_does_not_push_the_redelivery_further(db_session, fake_clock, sent):
    """The stale button stays on screen; pressing it again must not move the queue."""
    reminder, _, delivery = sent
    service = ReactionsService(db_session, fake_clock)

    await service.react(delivery.id, delivery.user_id, "snooze")
    fake_clock.advance(timedelta(minutes=1))
    await service.react(delivery.id, delivery.user_id, "snooze")

    stored = await reload(db_session, Delivery, delivery.id)
    assert stored.next_attempt_at == FROZEN_NOW + timedelta(minutes=reminder.snooze_minutes)
    assert await count_actions(db_session, delivery.id, ActionKind.SNOOZE) == 1


async def test_a_postponed_delivery_still_takes_a_final_answer(db_session, fake_clock, sent):
    """Snoozing is not answering, so a duplicate message can still close it."""
    _, occurrence, delivery = sent
    service = ReactionsService(db_session, fake_clock)

    await service.react(delivery.id, delivery.user_id, "snooze")
    result = await service.react(delivery.id, delivery.user_id, "done")

    assert result.applied is True
    stored = await reload(db_session, Delivery, delivery.id)
    assert stored.status is DeliveryStatus.DONE
    assert stored.reacted_at == FROZEN_NOW
    assert (await reload(db_session, Occurrence, occurrence.id)).status is OccurrenceStatus.DONE


async def test_a_reaction_releases_the_dispatcher_lease(db_session, fake_clock, sent):
    """A reacted row is nobody's to send; the lease dies with the answer."""
    _, _, delivery = sent
    await db_session.execute(
        sa.update(Delivery)
        .where(Delivery.id == delivery.id)
        .values(locked_until=FROZEN_NOW + timedelta(minutes=1))
    )
    await db_session.commit()

    await ReactionsService(db_session, fake_clock).react(delivery.id, delivery.user_id, "skip")

    stored = await reload(db_session, Delivery, delivery.id)
    assert stored.status is DeliveryStatus.SKIPPED
    assert stored.locked_until is None


async def test_a_closed_occurrence_refuses_a_late_reaction(db_session, fake_clock, sent):
    """The reaper already wrote its verdict; a late tap must not overwrite it."""
    _, occurrence, delivery = sent
    await db_session.execute(
        sa.update(Occurrence)
        .where(Occurrence.id == occurrence.id)
        .values(status=OccurrenceStatus.EXPIRED)
    )
    await db_session.commit()

    result = await ReactionsService(db_session, fake_clock).react(
        delivery.id, delivery.user_id, "done"
    )

    assert (result.applied, result.reason) == (False, RejectReason.EXPIRED)
    assert (await reload(db_session, Occurrence, occurrence.id)).status is OccurrenceStatus.EXPIRED
    assert await count_actions(db_session, delivery.id) == 0


async def test_a_snooze_lands_after_the_quiet_hours_rather_than_inside_them(
    db_session, fake_clock, user_factory, reminder_factory, occurrence_factory, delivery_factory
):
    """Ten more minutes at 22:55 means the morning, not five past eleven."""
    moscow = ZoneInfo("Europe/Moscow")
    night = datetime(2026, 6, 1, 19, 55, tzinfo=UTC)  # 22:55 local
    fake_clock.set(night)
    owner = await user_factory(
        timezone="Europe/Moscow", quiet_start=time(23, 0), quiet_end=time(7, 0)
    )
    reminder = await reminder_factory(owner=owner, snooze_minutes=15)
    occurrence = await occurrence_factory(
        reminder, fire_at=night - timedelta(minutes=5), expires_at=night + timedelta(hours=12)
    )
    delivery = await delivery_factory(
        occurrence, user_id=owner.id, status=DeliveryStatus.SENT, sent_at=night
    )
    await db_session.commit()

    result = await ReactionsService(db_session, fake_clock).react(delivery.id, owner.id, "snooze")

    morning = datetime(2026, 6, 2, 7, 0, tzinfo=moscow)
    assert result.snoozed_until.astimezone(moscow) == morning
    stored = await reload(db_session, Delivery, delivery.id)
    # The queue and the answer on screen name the same moment.
    assert stored.next_attempt_at == stored.snoozed_until == result.snoozed_until


async def test_a_snooze_is_never_postponed_past_the_moment_it_can_be_answered(
    db_session, fake_clock, user_factory, reminder_factory, occurrence_factory, delivery_factory
):
    """Silence outlasting the TTL would turn "remind me later" into "never"."""
    night = datetime(2026, 6, 1, 19, 55, tzinfo=UTC)  # 22:55 local
    fake_clock.set(night)
    owner = await user_factory(
        timezone="Europe/Moscow", quiet_start=time(23, 0), quiet_end=time(7, 0)
    )
    reminder = await reminder_factory(owner=owner, snooze_minutes=15)
    occurrence = await occurrence_factory(
        reminder, fire_at=night - timedelta(minutes=5), expires_at=night + timedelta(hours=2)
    )
    delivery = await delivery_factory(
        occurrence, user_id=owner.id, status=DeliveryStatus.SENT, sent_at=night
    )
    await db_session.commit()

    result = await ReactionsService(db_session, fake_clock).react(delivery.id, owner.id, "snooze")

    assert result.snoozed_until == night + timedelta(minutes=15)
    assert result.snoozed_until < occurrence.expires_at


async def test_quiet_hours_follow_the_user_not_the_reminder_snapshot(
    db_session, fake_clock, user_factory, reminder_factory, occurrence_factory, delivery_factory
):
    """`reminders.timezone` is a snapshot; the user may have moved since."""
    night = datetime(2026, 6, 1, 19, 55, tzinfo=UTC)  # 22:55 in Moscow
    fake_clock.set(night)
    owner = await user_factory(
        timezone="Europe/Moscow", quiet_start=time(23, 0), quiet_end=time(7, 0)
    )
    reminder = await reminder_factory(owner=owner, snooze_minutes=15, timezone="Asia/Vladivostok")
    occurrence = await occurrence_factory(
        reminder, fire_at=night - timedelta(minutes=5), expires_at=night + timedelta(hours=12)
    )
    delivery = await delivery_factory(
        occurrence, user_id=owner.id, status=DeliveryStatus.SENT, sent_at=night
    )
    await db_session.commit()

    result = await ReactionsService(db_session, fake_clock).react(delivery.id, owner.id, "snooze")

    assert result.snoozed_until.astimezone(ZoneInfo("Europe/Moscow")) == datetime(
        2026, 6, 2, 7, 0, tzinfo=ZoneInfo("Europe/Moscow")
    )
