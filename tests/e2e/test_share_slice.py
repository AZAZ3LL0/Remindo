"""S10 end to end: two people, one reminder, through real routers.

Acceptance criteria of tech.md 15 (S10): the owner hands out a deep link, the
invitee follows it and accepts, the reminder then reaches both, and either side
can end it, the owner by revoking and the watcher by unsubscribing.
"""

import sqlalchemy as sa
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import EditMessageText

from app.bot.callbacks import CatCb, PageCb, RemCb, ShareCb, WizCb, pack_wall_time
from app.db.models import Category, Delivery, Occurrence, Reminder, ReminderRecipient, User
from app.domain.contracts import RecipientRole
from app.domain.sharing import parse_invite_payload
from app.services.dispatching import DispatchingService
from app.services.planning import PlanningService
from tests.e2e.conftest import FRIEND_TG_USER_ID, TG_USER_ID

TIMEZONE = "Europe/Moscow"


async def seed_category(session_factory) -> int:
    async with session_factory() as session:
        water = Category(owner_id=None, code="water", title="Вода", emoji="💧", is_system=True)
        session.add(water)
        await session.commit()
        return water.id


async def fetch_reminder(session_factory) -> Reminder:
    async with session_factory() as session:
        return (await session.execute(sa.select(Reminder))).scalars().one()


async def fetch_user(session_factory, tg_user_id: int) -> User | None:
    async with session_factory() as session:
        stmt = sa.select(User).where(User.tg_user_id == tg_user_id)
        return (await session.execute(stmt)).scalars().one_or_none()


async def fetch_recipients(session_factory) -> list[ReminderRecipient]:
    async with session_factory() as session:
        stmt = sa.select(ReminderRecipient).order_by(ReminderRecipient.id)
        return list((await session.execute(stmt)).scalars().all())


async def first_fire_at(session_factory):
    """When the queue first goes off, so the dispatcher has something due."""
    async with session_factory() as session:
        stmt = sa.select(sa.func.min(Occurrence.fire_at))
        return (await session.execute(stmt)).scalar_one()


async def watchers(session_factory) -> list[ReminderRecipient]:
    return [
        row
        for row in await fetch_recipients(session_factory)
        if row.role is not RecipientRole.OWNER
    ]


async def deliveries_for(session_factory, user_id: int) -> list[Delivery]:
    async with session_factory() as session:
        stmt = sa.select(Delivery).where(Delivery.user_id == user_id).order_by(Delivery.id)
        return list((await session.execute(stmt)).scalars().all())


def last_text(telegram) -> str:
    return telegram.requests[-1].text


def said(telegram, fragment: str) -> bool:
    """Whether the fragment appears in anything the bot sent.

    A notice arrives before the screen that follows it (tech.md 22.5), so the
    last message is not always the one under test.
    """
    lowered = fragment.lower()
    return any(
        lowered in (getattr(request, "text", "") or "").lower() for request in telegram.requests
    )


def invite_link(telegram) -> str:
    """The link the owner was handed, picked out of what was actually sent."""
    for request in reversed(telegram.requests):
        text = getattr(request, "text", "") or ""
        if "?start=inv_" in text:
            return text.split("?start=")[1].split()[0]
    raise AssertionError("no invitation link was sent")


async def onboard(feeder) -> None:
    await feeder.message("/start")
    await feeder.message(TIMEZONE)


async def create_daily(feed, category_id: int, title: str = "Пить воду") -> None:
    await feed.message("/new")
    await feed.press(CatCb(category_id=category_id, action="pick").pack())
    await feed.message(title)
    await feed.press(WizCb(step="kind", value="daily").pack())
    await feed.press(WizCb(step="time", value=pack_wall_time("09:00")).pack())
    await feed.press(WizCb(step="times", value="ok").pack())
    await feed.press(WizCb(step="confirm", value="yes").pack())


async def share(feed, telegram, reminder_id: int) -> str:
    await feed.press(ShareCb(reminder_id=reminder_id, action="open").pack())
    await feed.press(ShareCb(reminder_id=reminder_id, action="invite").pack())
    return invite_link(telegram)


async def test_a_shared_reminder_reaches_both_people(
    feed, friend, telegram, session_factory, fake_clock, fake_bot, context
):
    """The whole promise of S10 in one run (tech.md 15)."""
    category_id = await seed_category(session_factory)
    await onboard(feed)
    await create_daily(feed, category_id)
    reminder = await fetch_reminder(session_factory)

    payload = await share(feed, telegram, reminder.id)

    # The friend meets the bot for the first time through the link. The
    # timezone question comes first, and the invitation waits (tech.md 22.5).
    await friend.message(f"/start {payload}")
    assert "таймзон" in last_text(telegram).lower()
    invitee = await fetch_user(session_factory, FRIEND_TG_USER_ID)
    assert invitee is not None

    await friend.message(TIMEZONE)
    assert "Пить воду" in last_text(telegram)

    await friend.press(ShareCb(reminder_id=reminder.id, action="accept").pack())

    async with session_factory() as session:
        await PlanningService(session, fake_clock, 48, 180).materialize()

    owner = await fetch_user(session_factory, TG_USER_ID)
    assert await deliveries_for(session_factory, owner.id) != []
    assert await deliveries_for(session_factory, invitee.id) != []

    fake_clock.set(await first_fire_at(session_factory))
    async with session_factory() as session:
        await DispatchingService(session, fake_clock, fake_bot, 100, 60).deliver()
    assert {message.chat_id for message in fake_bot.sent} == {
        owner.tg_chat_id,
        invitee.tg_chat_id,
    }


class TestFollowingALink:
    async def test_a_payload_that_is_not_an_invitation_says_so(
        self, feed, telegram, session_factory
    ):
        await seed_category(session_factory)
        await onboard(feed)
        await feed.message("/start something_else")
        assert said(telegram, "не похоже на приглашение")

    async def test_a_revoked_link_no_longer_works(self, feed, friend, telegram, session_factory):
        category_id = await seed_category(session_factory)
        await onboard(feed)
        await create_daily(feed, category_id)
        reminder = await fetch_reminder(session_factory)
        payload = await share(feed, telegram, reminder.id)

        await feed.press(ShareCb(reminder_id=reminder.id, action="revoke").pack())
        await friend.message(f"/start {payload}")

        assert said(telegram, "отозвано или просрочено")
        assert [row.role for row in await fetch_recipients(session_factory)] == [
            RecipientRole.OWNER
        ]

    async def test_the_owner_following_their_own_link_is_told_so(
        self, feed, telegram, session_factory
    ):
        category_id = await seed_category(session_factory)
        await onboard(feed)
        await create_daily(feed, category_id)
        reminder = await fetch_reminder(session_factory)
        payload = await share(feed, telegram, reminder.id)

        await feed.message(f"/start {payload}")

        assert [row.role for row in await fetch_recipients(session_factory)] == [
            RecipientRole.OWNER
        ]

    async def test_the_link_travels_whole_through_telegram(self, feed, telegram, session_factory):
        """A payload the parser cannot read back is a link nobody can follow."""
        category_id = await seed_category(session_factory)
        await onboard(feed)
        await create_daily(feed, category_id)
        reminder = await fetch_reminder(session_factory)

        payload = await share(feed, telegram, reminder.id)

        assert parse_invite_payload(payload)


class TestAnsweringTheInvitation:
    async def test_declining_leaves_the_reminder_alone(
        self, feed, friend, telegram, session_factory
    ):
        category_id = await seed_category(session_factory)
        await onboard(feed)
        await create_daily(feed, category_id)
        reminder = await fetch_reminder(session_factory)
        payload = await share(feed, telegram, reminder.id)

        await onboard(friend)
        await friend.message(f"/start {payload}")
        await friend.press(ShareCb(reminder_id=reminder.id, action="decline").pack())

        assert [row.role for row in await fetch_recipients(session_factory)] == [
            RecipientRole.OWNER
        ]

    async def test_accepting_twice_subscribes_once(
        self, feed, friend, telegram, session_factory, fake_clock
    ):
        """Idempotency (tech.md 10): the second press changes nothing."""
        category_id = await seed_category(session_factory)
        await onboard(feed)
        await create_daily(feed, category_id)
        reminder = await fetch_reminder(session_factory)
        payload = await share(feed, telegram, reminder.id)
        await onboard(friend)
        await friend.message(f"/start {payload}")

        async with session_factory() as session:
            await PlanningService(session, fake_clock, 48, 180).materialize()

        accept = ShareCb(reminder_id=reminder.id, action="accept").pack()
        await friend.press(accept)
        invitee = await fetch_user(session_factory, FRIEND_TG_USER_ID)
        after_first = await deliveries_for(session_factory, invitee.id)
        await friend.press(accept)

        assert after_first != []
        assert [row.id for row in await deliveries_for(session_factory, invitee.id)] == [
            row.id for row in after_first
        ]
        assert len(await watchers(session_factory)) == 1

    async def test_the_watcher_sees_the_reminder_in_shared_and_not_in_their_list(
        self, feed, friend, telegram, session_factory
    ):
        category_id = await seed_category(session_factory)
        await onboard(feed)
        await create_daily(feed, category_id)
        reminder = await fetch_reminder(session_factory)
        payload = await share(feed, telegram, reminder.id)
        await onboard(friend)
        await friend.message(f"/start {payload}")
        await friend.press(ShareCb(reminder_id=reminder.id, action="accept").pack())

        await friend.message("/list")
        assert "Напоминаний пока нет" in last_text(telegram)

        await friend.message("/shared")
        assert "Пить воду" in last_text(telegram)

        await friend.press(PageCb(scope="shared", page=0).pack())
        assert "Пить воду" in last_text(telegram)


class TestUnsubscribing:
    async def test_unsubscribing_stops_the_reminder_arriving(
        self, feed, friend, telegram, session_factory, fake_clock
    ):
        category_id = await seed_category(session_factory)
        await onboard(feed)
        await create_daily(feed, category_id)
        reminder = await fetch_reminder(session_factory)
        payload = await share(feed, telegram, reminder.id)
        await onboard(friend)
        await friend.message(f"/start {payload}")
        await friend.press(ShareCb(reminder_id=reminder.id, action="accept").pack())
        async with session_factory() as session:
            await PlanningService(session, fake_clock, 48, 180).materialize()

        invitee = await fetch_user(session_factory, FRIEND_TG_USER_ID)
        assert await deliveries_for(session_factory, invitee.id) != []

        await friend.press(ShareCb(reminder_id=reminder.id, action="leave").pack())
        assert "Отписаться" in last_text(telegram)
        await friend.press(ShareCb(reminder_id=reminder.id, action="confirm_leave").pack())

        assert await deliveries_for(session_factory, invitee.id) == []
        owner = await fetch_user(session_factory, TG_USER_ID)
        assert await deliveries_for(session_factory, owner.id) != []

    async def test_unsubscribing_twice_unsubscribes_once(
        self, feed, friend, telegram, session_factory
    ):
        """Idempotency (tech.md 10): the second press finds nothing to end."""
        category_id = await seed_category(session_factory)
        await onboard(feed)
        await create_daily(feed, category_id)
        reminder = await fetch_reminder(session_factory)
        payload = await share(feed, telegram, reminder.id)
        await onboard(friend)
        await friend.message(f"/start {payload}")
        await friend.press(ShareCb(reminder_id=reminder.id, action="accept").pack())

        leave = ShareCb(reminder_id=reminder.id, action="confirm_leave").pack()
        await friend.press(leave)
        await friend.press(leave)

        assert [row.role for row in await fetch_recipients(session_factory)] == [
            RecipientRole.OWNER
        ]

    async def test_the_owner_card_stops_counting_a_watcher_who_left(
        self, feed, friend, telegram, session_factory
    ):
        category_id = await seed_category(session_factory)
        await onboard(feed)
        await create_daily(feed, category_id)
        reminder = await fetch_reminder(session_factory)
        payload = await share(feed, telegram, reminder.id)
        await onboard(friend)
        await friend.message(f"/start {payload}")
        await friend.press(ShareCb(reminder_id=reminder.id, action="accept").pack())

        await feed.press(RemCb(reminder_id=reminder.id, action="open").pack())
        assert "Получателей кроме тебя: 1" in last_text(telegram)

        await friend.press(ShareCb(reminder_id=reminder.id, action="confirm_leave").pack())
        await feed.press(RemCb(reminder_id=reminder.id, action="open").pack())
        assert "Получателей" not in last_text(telegram)


class TestTelegramRefuses:
    """Error paths (tech.md 10.3): the transport fails, the state does not."""

    async def test_a_rate_limit_on_the_redraw_keeps_the_acceptance(
        self, feed, friend, telegram, session_factory
    ):
        category_id = await seed_category(session_factory)
        await onboard(feed)
        await create_daily(feed, category_id)
        reminder = await fetch_reminder(session_factory)
        payload = await share(feed, telegram, reminder.id)
        await onboard(friend)
        await friend.message(f"/start {payload}")

        telegram.fail_next(
            TelegramRetryAfter(method=EditMessageText(text="x"), message="flood", retry_after=5),
            on=EditMessageText,
        )
        await friend.press(ShareCb(reminder_id=reminder.id, action="accept").pack())

        assert all(row.accepted_at is not None for row in await watchers(session_factory))

    async def test_a_blocked_bot_does_not_unsubscribe_twice(
        self, feed, friend, telegram, session_factory
    ):
        category_id = await seed_category(session_factory)
        await onboard(feed)
        await create_daily(feed, category_id)
        reminder = await fetch_reminder(session_factory)
        payload = await share(feed, telegram, reminder.id)
        await onboard(friend)
        await friend.message(f"/start {payload}")
        await friend.press(ShareCb(reminder_id=reminder.id, action="accept").pack())

        telegram.fail_next(
            TelegramForbiddenError(method=EditMessageText(text="x"), message="blocked"),
            on=EditMessageText,
        )
        await friend.press(ShareCb(reminder_id=reminder.id, action="confirm_leave").pack())

        assert [row.role for row in await fetch_recipients(session_factory)] == [
            RecipientRole.OWNER
        ]

    async def test_a_redraw_that_changes_nothing_is_not_an_error(
        self, feed, telegram, session_factory
    ):
        category_id = await seed_category(session_factory)
        await onboard(feed)
        await create_daily(feed, category_id)
        reminder = await fetch_reminder(session_factory)

        opened = ShareCb(reminder_id=reminder.id, action="open").pack()
        await feed.press(opened)
        redraws = len(telegram.edits)
        await feed.press(opened)

        # Telegram answers an identical redraw with `message is not modified`.
        # The screen is already right, so that is the expected outcome.
        assert len(telegram.edits) == redraws + 1
        assert said(telegram, "Доступ к «Пить воду»")


async def test_the_planner_does_not_double_up_on_a_shared_reminder(
    feed, friend, telegram, session_factory, fake_clock
):
    """Idempotency of the planner cycle with two recipients (tech.md 10)."""
    category_id = await seed_category(session_factory)
    await onboard(feed)
    await create_daily(feed, category_id)
    reminder = await fetch_reminder(session_factory)
    payload = await share(feed, telegram, reminder.id)
    await onboard(friend)
    await friend.message(f"/start {payload}")
    await friend.press(ShareCb(reminder_id=reminder.id, action="accept").pack())

    async with session_factory() as session:
        first = await PlanningService(session, fake_clock, 48, 180).materialize()
    async with session_factory() as session:
        second = await PlanningService(session, fake_clock, 48, 180).materialize()

    assert first.deliveries_created > 0
    assert second.occurrences_created == 0
    assert second.deliveries_created == 0

    async with session_factory() as session:
        occurrences = int(
            (await session.execute(sa.select(sa.func.count()).select_from(Occurrence))).scalar_one()
        )
        deliveries = int(
            (await session.execute(sa.select(sa.func.count()).select_from(Delivery))).scalar_one()
        )
    assert deliveries == occurrences * 2
