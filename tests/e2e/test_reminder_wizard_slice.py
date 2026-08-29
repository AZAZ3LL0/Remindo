"""S3 end to end: update -> handler -> service -> db, through real routers.

Acceptance criteria of tech.md 15 (S3): the wizard walks category, title,
schedule kind and time, a one-off and a daily reminder both come out of it, the
card follows the creation, and confirming twice creates one reminder.
"""

from datetime import timedelta
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.methods import EditMessageText, GetMe

from app.bot.callbacks import CatCb, WizCb, pack_wall_time
from app.db.models import Category, Occurrence, Reminder, ReminderRecipient, User
from app.domain.contracts import RecipientRole, ReminderStatus, ScheduleKind
from app.domain.reminders import local_today
from app.domain.schedules import format_local_date
from app.services.planning import PlanningService
from tests.conftest import FROZEN_NOW
from tests.e2e.conftest import TG_USER_ID

TIMEZONE = "Europe/Moscow"
TODAY = local_today(FROZEN_NOW, ZoneInfo(TIMEZONE))
TOMORROW = TODAY + timedelta(days=1)


async def seed_category(session_factory) -> int:
    async with session_factory() as session:
        category = Category(owner_id=None, code="task", title="Задачи", emoji="📌", is_system=True)
        session.add(category)
        await session.commit()
        return category.id


async def fetch_user(session_factory) -> User:
    async with session_factory() as session:
        stmt = sa.select(User).where(User.tg_user_id == TG_USER_ID)
        return (await session.execute(stmt)).scalars().one()


async def reminders(session_factory) -> list[Reminder]:
    async with session_factory() as session:
        stmt = sa.select(Reminder).order_by(Reminder.id)
        return list((await session.execute(stmt)).scalars().all())


def last_text(telegram) -> str:
    return telegram.requests[-1].text


async def onboard(feed) -> None:
    await feed.message("/start")
    await feed.message(TIMEZONE)


async def start_wizard(feed, category_id: int, title: str = "Сдать отчёт") -> None:
    await feed.message("/new")
    await feed.press(CatCb(category_id=category_id, action="pick").pack())
    await feed.message(title)


async def build_once(feed, category_id: int, title: str = "Сдать отчёт") -> None:
    await start_wizard(feed, category_id, title)
    await feed.press(WizCb(step="kind", value="once").pack())
    await feed.press(WizCb(step="date", value="tmrw").pack())
    await feed.press(WizCb(step="at", value=pack_wall_time("09:00")).pack())


async def test_a_one_off_reminder_is_created_from_the_wizard(session_factory, feed, telegram):
    category_id = await seed_category(session_factory)
    await onboard(feed)

    await build_once(feed, category_id)
    assert "Сдать отчёт" in last_text(telegram)
    await feed.press(WizCb(step="confirm", value="yes").pack())

    created = await reminders(session_factory)
    assert [(item.title, item.schedule_kind, item.schedule) for item in created] == [
        ("Сдать отчёт", ScheduleKind.ONCE, {"kind": "once", "at": f"{TOMORROW.isoformat()}T09:00"})
    ]


async def test_a_daily_reminder_collects_several_times(session_factory, feed, telegram):
    category_id = await seed_category(session_factory)
    await onboard(feed)

    await start_wizard(feed, category_id, "Таблетки")
    await feed.press(WizCb(step="kind", value="daily").pack())
    await feed.press(WizCb(step="time", value=pack_wall_time("08:00")).pack())
    await feed.press(WizCb(step="time", value=pack_wall_time("20:00")).pack())
    await feed.press(WizCb(step="times", value="ok").pack())
    await feed.press(WizCb(step="confirm", value="yes").pack())

    created = await reminders(session_factory)
    assert [item.schedule for item in created] == [
        {"kind": "daily", "times": ["08:00", "20:00"], "every_n_days": 1}
    ]


async def test_a_chosen_time_is_removed_by_pressing_it_again(session_factory, feed, telegram):
    category_id = await seed_category(session_factory)
    await onboard(feed)

    await start_wizard(feed, category_id, "Таблетки")
    await feed.press(WizCb(step="kind", value="daily").pack())
    await feed.press(WizCb(step="time", value=pack_wall_time("08:00")).pack())
    await feed.press(WizCb(step="time", value=pack_wall_time("20:00")).pack())
    await feed.press(WizCb(step="time", value=pack_wall_time("08:00")).pack())
    await feed.press(WizCb(step="times", value="ok").pack())
    await feed.press(WizCb(step="confirm", value="yes").pack())

    assert [item.schedule["times"] for item in await reminders(session_factory)] == [["20:00"]]


async def test_finishing_a_daily_schedule_with_no_time_is_refused(session_factory, feed, telegram):
    category_id = await seed_category(session_factory)
    await onboard(feed)

    await start_wizard(feed, category_id, "Таблетки")
    await feed.press(WizCb(step="kind", value="daily").pack())
    await feed.press(WizCb(step="times", value="ok").pack())

    assert "хотя бы одно время" in telegram.answers[-1].text
    assert await reminders(session_factory) == []


async def test_a_typed_date_and_time_reach_the_schedule(session_factory, feed, telegram):
    category_id = await seed_category(session_factory)
    await onboard(feed)

    await start_wizard(feed, category_id)
    await feed.press(WizCb(step="kind", value="once").pack())
    await feed.press(WizCb(step="date", value="man").pack())
    await feed.message(format_local_date(TOMORROW))
    await feed.press(WizCb(step="at", value="man").pack())
    await feed.message("07:45")
    await feed.press(WizCb(step="confirm", value="yes").pack())

    assert [item.schedule["at"] for item in await reminders(session_factory)] == [
        f"{TOMORROW.isoformat()}T07:45"
    ]


async def test_a_date_already_gone_keeps_the_question_open(session_factory, feed, telegram):
    category_id = await seed_category(session_factory)
    await onboard(feed)

    await start_wizard(feed, category_id)
    await feed.press(WizCb(step="kind", value="once").pack())
    await feed.press(WizCb(step="date", value="man").pack())
    await feed.message(format_local_date(TODAY - timedelta(days=1)))

    assert "Не понял дату" in last_text(telegram)

    # The step survived the mistake, so the next attempt still counts.
    await feed.message(format_local_date(TOMORROW))
    await feed.press(WizCb(step="at", value=pack_wall_time("09:00")).pack())
    await feed.press(WizCb(step="confirm", value="yes").pack())

    assert len(await reminders(session_factory)) == 1


async def test_a_time_that_is_not_a_time_keeps_the_question_open(session_factory, feed, telegram):
    category_id = await seed_category(session_factory)
    await onboard(feed)

    await start_wizard(feed, category_id)
    await feed.press(WizCb(step="kind", value="once").pack())
    await feed.press(WizCb(step="date", value="tmrw").pack())
    await feed.message("четверть восьмого")

    assert "Не понял время" in last_text(telegram)
    assert await reminders(session_factory) == []


async def test_an_empty_title_keeps_the_question_open(session_factory, feed, telegram):
    category_id = await seed_category(session_factory)
    await onboard(feed)

    await feed.message("/new")
    await feed.press(CatCb(category_id=category_id, action="pick").pack())
    await feed.message("   ")

    assert "Название" in last_text(telegram)
    assert await reminders(session_factory) == []


async def test_a_one_off_moment_that_passed_while_confirming_is_refused(
    session_factory, feed, telegram, fake_clock
):
    """The confirmation screen is a promise; a stale one must not create a row."""
    category_id = await seed_category(session_factory)
    await onboard(feed)

    await build_once(feed, category_id)
    fake_clock.advance(timedelta(days=2))
    await feed.press(WizCb(step="confirm", value="yes").pack())

    assert "уже прошёл" in telegram.answers[-1].text
    assert await reminders(session_factory) == []


async def test_confirming_twice_creates_one_reminder(session_factory, feed, telegram):
    """The second press replays a stale button; the wizard is already finished."""
    category_id = await seed_category(session_factory)
    await onboard(feed)

    await build_once(feed, category_id)
    await feed.press(WizCb(step="confirm", value="yes").pack())
    await feed.press(WizCb(step="confirm", value="yes").pack())

    created = await reminders(session_factory)
    assert len(created) == 1
    async with session_factory() as session:
        recipients = await session.scalar(sa.select(sa.func.count()).select_from(ReminderRecipient))
    assert recipients == 1


async def test_cancelling_leaves_no_reminder(session_factory, feed, telegram):
    category_id = await seed_category(session_factory)
    await onboard(feed)

    await start_wizard(feed, category_id)
    await feed.press(WizCb(step="confirm", value="no").pack())

    assert await reminders(session_factory) == []
    assert "Отменено" in last_text(telegram)

    # The state is gone, so the schedule buttons no longer do anything.
    await feed.press(WizCb(step="kind", value="once").pack())
    assert await reminders(session_factory) == []


async def test_the_card_after_creation_names_the_next_firing_moment(
    session_factory, feed, telegram
):
    category_id = await seed_category(session_factory)
    await onboard(feed)

    await build_once(feed, category_id)
    await feed.press(WizCb(step="confirm", value="yes").pack())

    card = last_text(telegram)
    assert "Сдать отчёт" in card
    assert "активно" in card
    assert TOMORROW.strftime("%d.%m 09:00") in card


async def test_the_planner_picks_up_what_the_wizard_created(
    session_factory, feed, fake_clock, settings
):
    """The slice ends at the row; the queue proves the row is usable."""
    category_id = await seed_category(session_factory)
    await onboard(feed)

    await build_once(feed, category_id)
    await feed.press(WizCb(step="confirm", value="yes").pack())

    async with session_factory() as session:
        planned = await PlanningService(
            session,
            fake_clock,
            horizon_hours=settings.planner_horizon_hours,
            occurrence_ttl_minutes=settings.occurrence_ttl_minutes,
        ).materialize()

    assert planned.occurrences_created == 1
    async with session_factory() as session:
        moment = await session.scalar(sa.select(sa.func.min(Occurrence.scheduled_for)))
    assert moment.astimezone(ZoneInfo(TIMEZONE)).date() == TOMORROW


async def test_a_created_reminder_starts_active_and_owned(session_factory, feed):
    category_id = await seed_category(session_factory)
    await onboard(feed)

    await build_once(feed, category_id)
    await feed.press(WizCb(step="confirm", value="yes").pack())

    user = await fetch_user(session_factory)
    created = (await reminders(session_factory))[0]
    async with session_factory() as session:
        recipient = (
            (
                await session.execute(
                    sa.select(ReminderRecipient).where(
                        ReminderRecipient.role == RecipientRole.OWNER
                    )
                )
            )
            .scalars()
            .one()
        )

    assert created.status is ReminderStatus.ACTIVE
    assert created.owner_id == user.id
    assert created.timezone == TIMEZONE
    assert recipient.user_id == user.id
    assert recipient.accepted_at is not None


class TestTelegramRefuses:
    """The transport fails; the row and the wizard must not (tech.md 10)."""

    async def test_a_redraw_that_changes_nothing_is_not_an_error(
        self, session_factory, feed, telegram
    ):
        """Telegram answers an identical edit with `message is not modified`."""
        category_id = await seed_category(session_factory)
        await onboard(feed)
        await start_wizard(feed, category_id, "Таблетки")
        await feed.press(WizCb(step="kind", value="daily").pack())

        telegram.fail_next(
            TelegramBadRequest(method=GetMe(), message="Bad Request: message is not modified"),
            on=EditMessageText,
        )
        await feed.press(WizCb(step="time", value=pack_wall_time("08:00")).pack())

        assert not [answer for answer in telegram.answers if answer.text]

    async def test_a_rate_limit_keeps_the_created_reminder(self, session_factory, feed, telegram):
        """The commit happened before the card, so the row must survive it."""
        category_id = await seed_category(session_factory)
        await onboard(feed)
        await build_once(feed, category_id)

        telegram.fail_next(
            TelegramRetryAfter(method=GetMe(), message="Flood", retry_after=5),
            on=EditMessageText,
        )
        await feed.press(WizCb(step="confirm", value="yes").pack())

        assert len(await reminders(session_factory)) == 1
        assert telegram.answers[-1].text == "Что-то пошло не так. Попробуй ещё раз."

    async def test_a_blocked_bot_does_not_create_a_second_reminder(
        self, session_factory, feed, telegram
    ):
        """A failed card must not leave the wizard able to confirm again."""
        category_id = await seed_category(session_factory)
        await onboard(feed)
        await build_once(feed, category_id)

        telegram.fail_next(
            TelegramForbiddenError(method=GetMe(), message="blocked"), on=EditMessageText
        )
        await feed.press(WizCb(step="confirm", value="yes").pack())
        await feed.press(WizCb(step="confirm", value="yes").pack())

        assert len(await reminders(session_factory)) == 1
