"""digest.send acceptance criteria (tech.md 23.5).

The cycle is judged by what a user ends up receiving: one digest per local
week, none for a week they did nothing in, and none at all once they turn it
off. Running it twice must change nothing the first run did not.
"""

from datetime import UTC, datetime, time, timedelta

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

from app.db.models import DeliveryAction, User
from app.domain.contracts import ActionKind, DeliveryStatus, OccurrenceStatus
from app.services.digest import DigestService

#: Monday 09:00 in Europe/Moscow, the moment every digest in this file is keyed
#: on. `FROZEN_NOW` is that same Monday at noon local, so the week just closed.
MONDAY_NINE = datetime(2026, 6, 1, 6, 0, tzinfo=UTC)
MONDAY_NOON = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)


def build_service(session, clock, gateway, batch_size: int = 100) -> DigestService:
    return DigestService(session, clock, gateway, weekday=1, hour=9, batch_size=batch_size)


@pytest.fixture
async def reacted(db_session, user_factory, reminder_factory, occurrence_factory, delivery_factory):
    """A user who answered one reminder during the week that just ended."""

    async def _build(
        user: User | None = None,
        when: datetime | None = None,
        category=None,
        **overrides,
    ) -> User:
        user = user or await user_factory(
            onboarded_at=MONDAY_NINE - timedelta(days=30), **overrides
        )
        reminder = await reminder_factory(owner=user, category=category)
        occurrence = await occurrence_factory(
            reminder,
            fire_at=when or MONDAY_NINE - timedelta(days=2),
            status=OccurrenceStatus.DONE,
        )
        delivery = await delivery_factory(occurrence, user_id=user.id, status=DeliveryStatus.DONE)
        db_session.add(
            DeliveryAction(
                delivery_id=delivery.id,
                user_id=user.id,
                kind=ActionKind.DONE,
                payload={},
                created_at=when or MONDAY_NINE - timedelta(days=2),
            )
        )
        await db_session.commit()
        return user

    return _build


@pytest.fixture
async def silent_user(db_session, user_factory):
    """Onboarded, but with nothing in the journal."""
    user = await user_factory(onboarded_at=MONDAY_NINE - timedelta(days=30))
    await db_session.commit()
    return user


async def reload(session, user_id: int) -> User:
    return await session.get(User, user_id, populate_existing=True)


async def test_a_week_with_reactions_produces_one_digest(db_session, fake_clock, fake_bot, reacted):
    user = await reacted()
    fake_clock.set(MONDAY_NOON)

    result = await build_service(db_session, fake_clock, fake_bot).run()

    assert result.sent == 1
    assert [message.chat_id for message in fake_bot.sent] == [user.tg_chat_id]
    assert (await reload(db_session, user.id)).digest_sent_at == MONDAY_NINE


async def test_running_the_cycle_twice_sends_one_digest(db_session, fake_clock, fake_bot, reacted):
    """Idempotency: the weekly moment is the key, and it does not move."""
    user = await reacted()
    fake_clock.set(MONDAY_NOON)
    service = build_service(db_session, fake_clock, fake_bot)

    first = await service.run()
    second = await service.run()

    assert (first.sent, second.sent) == (1, 0)
    assert len(fake_bot.sent) == 1
    assert (await reload(db_session, user.id)).digest_sent_at == MONDAY_NINE


async def test_a_later_tick_in_the_same_week_sends_nothing_more(
    db_session, fake_clock, fake_bot, reacted
):
    """The mark is the week, not the minute: the cycle wakes sixty times an hour."""
    await reacted()
    fake_clock.set(MONDAY_NOON)
    await build_service(db_session, fake_clock, fake_bot).run()

    fake_clock.set(MONDAY_NOON + timedelta(days=3))
    assert (await build_service(db_session, fake_clock, fake_bot).run()).sent == 0
    assert len(fake_bot.sent) == 1


async def test_the_next_week_is_owed_again(db_session, fake_clock, fake_bot, reacted):
    user = await reacted()
    fake_clock.set(MONDAY_NOON)
    await build_service(db_session, fake_clock, fake_bot).run()

    await reacted(user=user, when=MONDAY_NINE + timedelta(days=3))
    fake_clock.set(MONDAY_NOON + timedelta(days=7))
    result = await build_service(db_session, fake_clock, fake_bot).run()

    assert result.sent == 1
    assert len(fake_bot.sent) == 2
    assert (await reload(db_session, user.id)).digest_sent_at == MONDAY_NINE + timedelta(days=7)


async def test_an_empty_week_is_marked_but_not_sent(db_session, fake_clock, fake_bot, silent_user):
    """A digest saying nothing happened is a message nobody asked for; the mark
    still goes down, or the cycle returns every minute all week."""
    fake_clock.set(MONDAY_NOON)

    result = await build_service(db_session, fake_clock, fake_bot).run()

    assert (result.empty, result.sent) == (1, 0)
    assert fake_bot.sent == []
    assert (await reload(db_session, silent_user.id)).digest_sent_at == MONDAY_NINE


async def test_a_switched_off_digest_is_never_built(
    db_session, fake_clock, fake_bot, reacted, user_factory
):
    user = await user_factory(onboarded_at=MONDAY_NINE - timedelta(days=30), digest_enabled=False)
    await reacted(user=user)
    fake_clock.set(MONDAY_NOON)

    result = await build_service(db_session, fake_clock, fake_bot).run()

    assert (result.considered, result.sent) == (0, 0)
    assert fake_bot.sent == []
    assert (await reload(db_session, user.id)).digest_sent_at is None


async def test_a_user_who_never_finished_onboarding_gets_nothing(
    db_session, fake_clock, fake_bot, user_factory
):
    """Without a timezone there is no local Monday to key the digest on."""
    await user_factory(onboarded_at=None)
    await db_session.commit()
    fake_clock.set(MONDAY_NOON)

    assert (await build_service(db_session, fake_clock, fake_bot).run()).considered == 0


async def test_silence_holds_the_digest_and_then_lets_it_through(
    db_session, fake_clock, fake_bot, reacted, user_factory
):
    """The quiet hours rule reaches the digest too (tech.md 23.6)."""
    user = await user_factory(
        onboarded_at=MONDAY_NINE - timedelta(days=30),
        quiet_start=time(8, 0),
        quiet_end=time(14, 0),
    )
    await reacted(user=user)

    fake_clock.set(MONDAY_NOON)
    assert (await build_service(db_session, fake_clock, fake_bot).run()).deferred == 1
    assert fake_bot.sent == []

    fake_clock.set(datetime(2026, 6, 1, 11, 30, tzinfo=UTC))  # 14:30 Moscow
    result = await build_service(db_session, fake_clock, fake_bot).run()

    assert result.sent == 1
    # Still keyed on the unshifted moment: the silence delayed the send, it did
    # not rename the week.
    assert (await reload(db_session, user.id)).digest_sent_at == MONDAY_NINE


async def test_a_blocked_chat_stops_the_digest_and_the_user(
    db_session, fake_clock, fake_bot, reacted
):
    user = await reacted()
    fake_clock.set(MONDAY_NOON)
    fake_bot.fail_next(TelegramForbiddenError(method=None, message="bot was blocked"))

    result = await build_service(db_session, fake_clock, fake_bot).run()

    assert result.blocked == 1
    updated = await reload(db_session, user.id)
    assert updated.is_blocked is True
    assert updated.digest_sent_at == MONDAY_NINE

    # The mark and the block both hold: a second tick does not try again.
    assert (await build_service(db_session, fake_clock, fake_bot).run()).considered == 0


async def test_a_malformed_message_is_not_retried(db_session, fake_clock, fake_bot, reacted):
    user = await reacted()
    fake_clock.set(MONDAY_NOON)
    fake_bot.fail_next(TelegramBadRequest(method=None, message="text is too long"))

    result = await build_service(db_session, fake_clock, fake_bot).run()

    assert result.failed == 1
    assert (await reload(db_session, user.id)).digest_sent_at == MONDAY_NINE
    assert (await build_service(db_session, fake_clock, fake_bot).run()).sent == 0


async def test_a_retry_after_leaves_the_week_owed(db_session, fake_clock, fake_bot, reacted):
    """Nothing is marked, so the next tick picks the same moment up again."""
    user = await reacted()
    fake_clock.set(MONDAY_NOON)
    fake_bot.fail_next(TelegramRetryAfter(method=None, message="flood", retry_after=5))

    first = await build_service(db_session, fake_clock, fake_bot).run()

    assert first.deferred == 1
    assert (await reload(db_session, user.id)).digest_sent_at is None

    fake_clock.set(MONDAY_NOON + timedelta(minutes=1))
    second = await build_service(db_session, fake_clock, fake_bot).run()

    assert second.sent == 1
    assert (await reload(db_session, user.id)).digest_sent_at == MONDAY_NINE


async def test_one_failure_does_not_cost_the_batch_its_week(
    db_session, fake_clock, fake_bot, reacted, user_factory
):
    blocked = await reacted()
    other = await reacted()
    fake_clock.set(MONDAY_NOON)
    fake_bot.fail_next(TelegramForbiddenError(method=None, message="bot was blocked"))

    result = await build_service(db_session, fake_clock, fake_bot).run()

    assert (result.blocked, result.sent) == (1, 1)
    assert [message.chat_id for message in fake_bot.sent] == [other.tg_chat_id]
    assert (await reload(db_session, blocked.id)).digest_sent_at == MONDAY_NINE


async def test_the_digest_counts_only_the_week_it_covers(
    db_session, fake_clock, fake_bot, reacted, user_factory
):
    """A reaction from three weeks back belongs to the monthly figure, not here."""
    user = await user_factory(onboarded_at=MONDAY_NINE - timedelta(days=60))
    await reacted(user=user, when=MONDAY_NINE - timedelta(days=20))
    fake_clock.set(MONDAY_NOON)

    result = await build_service(db_session, fake_clock, fake_bot).run()

    assert (result.empty, result.sent) == (1, 0)


async def test_the_digest_breaks_the_week_down_by_category(
    db_session, fake_clock, fake_bot, reacted, category_factory, user_factory
):
    """The breakdown is what makes a digest more than one number."""
    user = await user_factory(onboarded_at=MONDAY_NINE - timedelta(days=30))
    water = await category_factory(code="water_digest", title="Вода", emoji="💧")
    pills = await category_factory(code="pills_digest", title="Таблетки", emoji="💊")

    await reacted(user=user, category=water)
    await reacted(user=user, category=pills, when=MONDAY_NINE - timedelta(days=1))
    fake_clock.set(MONDAY_NOON)

    await build_service(db_session, fake_clock, fake_bot).run()

    text = fake_bot.sent[0].text
    assert "Вода" in text and "Таблетки" in text
