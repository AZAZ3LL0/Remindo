"""S6 end to end: wizard -> planner -> dispatcher -> button -> edited message.

Acceptance criteria of tech.md 15 (S6): the three buttons answer a delivered
reminder, the message loses them once it is answered, and pressing the same
button twice has exactly one effect.
"""

from datetime import timedelta

import pytest_asyncio
import sqlalchemy as sa
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import EditMessageText

from app.bot.callbacks import CatCb, ReactCb, WizCb, pack_wall_time
from app.bot.render.texts import T
from app.db.models import Category, Delivery, DeliveryAction, Occurrence
from app.domain.contracts import ActionKind, DeliveryStatus, OccurrenceStatus
from app.services.dispatching import DispatchingService
from app.services.planning import PlanningService

TIMEZONE = "Europe/Moscow"
LANG = "ru"
DAILY_TIME = "08:00"
#: Default step of the snooze button for a reminder the wizard creates.
SNOOZE_MINUTES = 10
#: Text the feeder puts on the message a button is pressed under.
PRESSED_MESSAGE = "напоминание"


@pytest_asyncio.fixture
async def water_category(session_factory) -> int:
    async with session_factory() as session:
        category = Category(owner_id=None, code="water", title="Вода", emoji="💧", is_system=True)
        session.add(category)
        await session.commit()
        return category.id


async def create_daily_reminder(feed, category_id: int) -> None:
    await feed.message("/start")
    await feed.message(TIMEZONE)
    await feed.message("/new")
    await feed.press(CatCb(category_id=category_id, action="pick").pack())
    await feed.message("Пить воду")
    await feed.press(WizCb(step="kind", value="daily").pack())
    await feed.press(WizCb(step="time", value=pack_wall_time(DAILY_TIME)).pack())
    await feed.press(WizCb(step="times", value="ok").pack())
    await feed.press(WizCb(step="confirm", value="yes").pack())


async def dispatch(session_factory, fake_clock, fake_bot):
    async with session_factory() as session:
        return await DispatchingService(
            session, fake_clock, fake_bot, batch_size=10, lock_seconds=60
        ).deliver()


async def deliver_first_reminder(session_factory, feed, fake_clock, fake_bot, settings, category):
    """Everything up to the moment the user is looking at a reminder."""
    await create_daily_reminder(feed, category)
    async with session_factory() as session:
        await PlanningService(
            session,
            fake_clock,
            horizon_hours=settings.planner_horizon_hours,
            occurrence_ttl_minutes=settings.occurrence_ttl_minutes,
        ).materialize()
    async with session_factory() as session:
        fake_clock.set(
            (await session.execute(sa.select(sa.func.min(Occurrence.fire_at)))).scalar_one()
        )
    await dispatch(session_factory, fake_clock, fake_bot)
    return buttons_of(fake_bot.sent[-1])


def buttons_of(message):
    return {
        ReactCb.unpack(button.callback_data).action: button.callback_data
        for row in message.keyboard.inline_keyboard
        for button in row
    }


async def fetch_delivery(session_factory) -> Delivery:
    async with session_factory() as session:
        stmt = sa.select(Delivery).order_by(Delivery.id).limit(1)
        return (await session.execute(stmt)).scalars().one()


async def fetch_actions(session_factory) -> list[ActionKind]:
    async with session_factory() as session:
        stmt = sa.select(DeliveryAction.kind).order_by(DeliveryAction.id)
        return list((await session.execute(stmt)).scalars().all())


async def fetch_occurrence(session_factory, occurrence_id: int) -> Occurrence:
    async with session_factory() as session:
        return await session.get(Occurrence, occurrence_id)


async def test_done_closes_the_message_and_a_second_tap_changes_nothing(
    session_factory, feed, fake_clock, fake_bot, telegram, settings, water_category
):
    buttons = await deliver_first_reminder(
        session_factory, feed, fake_clock, fake_bot, settings, water_category
    )

    await feed.press(buttons["done"])

    delivery = await fetch_delivery(session_factory)
    assert delivery.status is DeliveryStatus.DONE
    assert delivery.reacted_at is not None
    occurrence = await fetch_occurrence(session_factory, delivery.occurrence_id)
    assert occurrence.status is OccurrenceStatus.DONE
    assert await fetch_actions(session_factory) == [ActionKind.DONE]

    # The message keeps its reminder, gains the answer and loses its buttons.
    redraw = telegram.edits[-1]
    assert redraw.text.startswith(PRESSED_MESSAGE)
    assert redraw.text.endswith(T("react.done", LANG))
    assert redraw.reply_markup is None
    assert telegram.answers[-1].text == T("react.done", LANG)

    await feed.press(buttons["done"])

    assert await fetch_actions(session_factory) == [ActionKind.DONE]
    assert (await fetch_delivery(session_factory)).status is DeliveryStatus.DONE
    assert telegram.answers[-1].text == T("react.already", LANG)


async def test_skip_records_the_miss(
    session_factory, feed, fake_clock, fake_bot, telegram, settings, water_category
):
    buttons = await deliver_first_reminder(
        session_factory, feed, fake_clock, fake_bot, settings, water_category
    )

    await feed.press(buttons["skip"])

    delivery = await fetch_delivery(session_factory)
    assert delivery.status is DeliveryStatus.SKIPPED
    occurrence = await fetch_occurrence(session_factory, delivery.occurrence_id)
    assert occurrence.status is OccurrenceStatus.SKIPPED
    assert await fetch_actions(session_factory) == [ActionKind.SKIP]
    assert telegram.answers[-1].text == T("react.skipped", LANG)


async def test_snooze_brings_the_same_reminder_back(
    session_factory, feed, fake_clock, fake_bot, settings, water_category
):
    """Postponing returns the reminder to the queue instead of dropping it."""
    buttons = await deliver_first_reminder(
        session_factory, feed, fake_clock, fake_bot, settings, water_category
    )

    await feed.press(buttons["snooze"])

    postponed = await fetch_delivery(session_factory)
    assert postponed.status is DeliveryStatus.SNOOZED
    assert postponed.snoozed_until == fake_clock.now() + timedelta(minutes=SNOOZE_MINUTES)
    assert postponed.next_attempt_at == postponed.snoozed_until

    # Nothing goes out before the snooze runs out.
    assert (await dispatch(session_factory, fake_clock, fake_bot)).claimed == 0

    fake_clock.advance(timedelta(minutes=SNOOZE_MINUTES, seconds=1))
    assert (await dispatch(session_factory, fake_clock, fake_bot)).sent == 1
    assert len(fake_bot.sent) == 2

    # The reminder that came back answers like any other.
    await feed.press(buttons_of(fake_bot.sent[-1])["done"])

    assert (await fetch_delivery(session_factory)).status is DeliveryStatus.DONE
    assert await fetch_actions(session_factory) == [ActionKind.SNOOZE, ActionKind.DONE]


async def test_a_refused_redraw_keeps_the_reaction(
    session_factory, feed, fake_clock, fake_bot, telegram, settings, water_category
):
    """Telegram refusing the edit must not tell the user their tap failed."""
    buttons = await deliver_first_reminder(
        session_factory, feed, fake_clock, fake_bot, settings, water_category
    )
    telegram.fail_next(
        TelegramBadRequest(method=None, message="message can't be edited"), on=EditMessageText
    )

    await feed.press(buttons["done"])

    assert (await fetch_delivery(session_factory)).status is DeliveryStatus.DONE
    assert await fetch_actions(session_factory) == [ActionKind.DONE]
    assert telegram.answers[-1].text == T("react.done", LANG)
    assert T("error.generic", LANG) not in [answer.text for answer in telegram.answers]
