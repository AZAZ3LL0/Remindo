"""Reaction acceptance criteria (tech.md 7.4)."""

from datetime import timedelta

import pytest
import sqlalchemy as sa

from app.db.models import Delivery, DeliveryAction, Occurrence
from app.domain.contracts import ActionKind, DeliveryStatus, OccurrenceStatus
from app.domain.errors import NotFoundError, PermissionDeniedError
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
    assert second.reason == "already_handled"
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
    assert result.reason == "expired"
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
