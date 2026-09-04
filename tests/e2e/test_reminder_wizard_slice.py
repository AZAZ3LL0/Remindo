"""S3 end to end: update -> handler -> service -> db, through real routers.

Acceptance criteria of tech.md 15 (S3): the wizard walks category, title,
schedule kind and time, a one-off and a daily reminder both come out of it, the
card follows the creation, and confirming twice creates one reminder.
"""

from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.methods import EditMessageText, GetMe

from app.bot.callbacks import CatCb, WizCb, pack_wall_time, pack_window
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


async def test_a_weekly_reminder_collects_days_and_then_times(session_factory, feed, telegram):
    """S7 acceptance: weekdays and times both reach the payload, in that order."""
    category_id = await seed_category(session_factory)
    await onboard(feed)

    await start_wizard(feed, category_id, "Зарядка")
    await feed.press(WizCb(step="kind", value="weekly").pack())
    await feed.press(WizCb(step="wday", value="1").pack())
    await feed.press(WizCb(step="wday", value="3").pack())
    await feed.press(WizCb(step="wday", value="5").pack())
    await feed.press(WizCb(step="wday", value="ok").pack())
    await feed.press(WizCb(step="time", value=pack_wall_time("07:00")).pack())
    await feed.press(WizCb(step="times", value="ok").pack())
    await feed.press(WizCb(step="confirm", value="yes").pack())

    created = await reminders(session_factory)
    assert [(item.schedule_kind, item.schedule) for item in created] == [
        (
            ScheduleKind.WEEKLY,
            {"kind": "weekly", "times": ["07:00"], "weekdays": [1, 3, 5]},
        )
    ]


async def test_a_chosen_weekday_is_removed_by_pressing_it_again(session_factory, feed, telegram):
    category_id = await seed_category(session_factory)
    await onboard(feed)

    await start_wizard(feed, category_id, "Зарядка")
    await feed.press(WizCb(step="kind", value="weekly").pack())
    await feed.press(WizCb(step="wday", value="2").pack())
    await feed.press(WizCb(step="wday", value="6").pack())
    await feed.press(WizCb(step="wday", value="2").pack())
    await feed.press(WizCb(step="wday", value="ok").pack())
    await feed.press(WizCb(step="time", value=pack_wall_time("07:00")).pack())
    await feed.press(WizCb(step="times", value="ok").pack())
    await feed.press(WizCb(step="confirm", value="yes").pack())

    assert [item.schedule["weekdays"] for item in await reminders(session_factory)] == [[6]]


async def test_finishing_a_week_with_no_day_is_refused(session_factory, feed, telegram):
    category_id = await seed_category(session_factory)
    await onboard(feed)

    await start_wizard(feed, category_id, "Зарядка")
    await feed.press(WizCb(step="kind", value="weekly").pack())
    await feed.press(WizCb(step="wday", value="ok").pack())

    assert "хотя бы один день" in telegram.answers[-1].text
    assert await reminders(session_factory) == []


async def test_a_monthly_reminder_asks_what_a_short_month_does(session_factory, feed, telegram):
    """S7 acceptance: `on_missing_day` is a question, not a hidden default."""
    category_id = await seed_category(session_factory)
    await onboard(feed)

    await start_wizard(feed, category_id, "Оплатить счёт")
    await feed.press(WizCb(step="kind", value="monthly").pack())
    await feed.press(WizCb(step="mday", value="31").pack())
    await feed.press(WizCb(step="mday", value="ok").pack())

    assert "нет такого числа" in last_text(telegram)

    await feed.press(WizCb(step="miss", value="skip").pack())
    await feed.press(WizCb(step="time", value=pack_wall_time("12:00")).pack())
    await feed.press(WizCb(step="times", value="ok").pack())
    await feed.press(WizCb(step="confirm", value="yes").pack())

    created = await reminders(session_factory)
    assert [(item.schedule_kind, item.schedule) for item in created] == [
        (
            ScheduleKind.MONTHLY,
            {"kind": "monthly", "times": ["12:00"], "days": [31], "on_missing_day": "skip"},
        )
    ]


async def test_the_last_day_rule_reaches_the_payload(session_factory, feed, telegram):
    category_id = await seed_category(session_factory)
    await onboard(feed)

    await start_wizard(feed, category_id, "Оплатить счёт")
    await feed.press(WizCb(step="kind", value="monthly").pack())
    await feed.press(WizCb(step="mday", value="30").pack())
    await feed.press(WizCb(step="mday", value="ok").pack())
    await feed.press(WizCb(step="miss", value="last").pack())
    await feed.press(WizCb(step="time", value=pack_wall_time("12:00")).pack())
    await feed.press(WizCb(step="times", value="ok").pack())
    await feed.press(WizCb(step="confirm", value="yes").pack())

    assert [item.schedule["on_missing_day"] for item in await reminders(session_factory)] == [
        "last_day"
    ]


async def test_finishing_a_month_with_no_day_is_refused(session_factory, feed, telegram):
    category_id = await seed_category(session_factory)
    await onboard(feed)

    await start_wizard(feed, category_id, "Оплатить счёт")
    await feed.press(WizCb(step="kind", value="monthly").pack())
    await feed.press(WizCb(step="mday", value="ok").pack())

    assert "хотя бы одно число" in telegram.answers[-1].text
    assert await reminders(session_factory) == []


async def test_an_interval_reminder_is_created_with_its_window(session_factory, feed, telegram):
    category_id = await seed_category(session_factory)
    await onboard(feed)

    await start_wizard(feed, category_id, "Пить воду")
    await feed.press(WizCb(step="kind", value="interval").pack())
    await feed.press(WizCb(step="every", value="120").pack())
    await feed.press(WizCb(step="window", value=pack_window("09:00", "21:00")).pack())
    await feed.press(WizCb(step="confirm", value="yes").pack())

    created = await reminders(session_factory)
    assert [(item.schedule_kind, item.schedule) for item in created] == [
        (
            ScheduleKind.INTERVAL,
            {
                "kind": "interval",
                "every_minutes": 120,
                "window_start": "09:00",
                "window_end": "21:00",
            },
        )
    ]


async def test_a_typed_interval_and_window_reach_the_schedule(session_factory, feed, telegram):
    """The manual buttons used to lead nowhere; now they take text."""
    category_id = await seed_category(session_factory)
    await onboard(feed)

    await start_wizard(feed, category_id, "Пить воду")
    await feed.press(WizCb(step="kind", value="interval").pack())
    await feed.press(WizCb(step="every", value="man").pack())
    await feed.message("45")
    await feed.press(WizCb(step="window", value="man").pack())
    await feed.message("10:15-19:45")
    await feed.press(WizCb(step="confirm", value="yes").pack())

    assert [item.schedule for item in await reminders(session_factory)] == [
        {
            "kind": "interval",
            "every_minutes": 45,
            "window_start": "10:15",
            "window_end": "19:45",
        }
    ]


async def test_an_interval_outside_the_contract_keeps_the_question_open(
    session_factory, feed, telegram
):
    category_id = await seed_category(session_factory)
    await onboard(feed)

    await start_wizard(feed, category_id, "Пить воду")
    await feed.press(WizCb(step="kind", value="interval").pack())
    await feed.press(WizCb(step="every", value="man").pack())
    await feed.message("2")

    assert "Интервал от" in last_text(telegram)

    # The step survived the mistake, so the next attempt still counts.
    await feed.message("45")
    await feed.press(WizCb(step="window", value=pack_window("09:00", "21:00")).pack())
    await feed.press(WizCb(step="confirm", value="yes").pack())

    assert len(await reminders(session_factory)) == 1


async def test_a_window_that_is_not_a_window_keeps_the_question_open(
    session_factory, feed, telegram
):
    category_id = await seed_category(session_factory)
    await onboard(feed)

    await start_wizard(feed, category_id, "Пить воду")
    await feed.press(WizCb(step="kind", value="interval").pack())
    await feed.press(WizCb(step="every", value="60").pack())
    await feed.press(WizCb(step="window", value="man").pack())
    await feed.message("с утра до вечера")

    assert "Не понял окно" in last_text(telegram)
    assert await reminders(session_factory) == []


@pytest.mark.parametrize(
    ("kind", "steps"),
    [
        ("weekly", [("wday", "1"), ("wday", "ok")]),
        ("monthly", [("mday", "1"), ("mday", "ok"), ("miss", "last")]),
        ("interval", [("every", "60")]),
    ],
)
async def test_every_new_screen_can_be_cancelled(session_factory, feed, telegram, kind, steps):
    """A screen without a way out is a wizard the user leaves by restarting."""
    category_id = await seed_category(session_factory)
    await onboard(feed)

    await start_wizard(feed, category_id, "Что-нибудь")
    await feed.press(WizCb(step="kind", value=kind).pack())
    for step, value in steps:
        await feed.press(WizCb(step=step, value=value).pack())

    await feed.press(WizCb(step="confirm", value="no").pack())

    assert "Отменено" in last_text(telegram)
    assert await reminders(session_factory) == []


@pytest.mark.parametrize(
    ("step", "value"),
    [("wday", "9"), ("wday", "мимо"), ("mday", "0"), ("miss", "maybe"), ("every", "часто")],
)
async def test_a_crafted_atom_on_a_new_step_changes_nothing(
    session_factory, feed, telegram, step, value
):
    """Only a hand-made press gets here, so it is answered with silence."""
    category_id = await seed_category(session_factory)
    await onboard(feed)

    await start_wizard(feed, category_id, "Что-нибудь")
    kind = {"wday": "weekly", "mday": "monthly", "miss": "monthly", "every": "interval"}[step]
    await feed.press(WizCb(step="kind", value=kind).pack())
    if step == "miss":
        await feed.press(WizCb(step="mday", value="1").pack())
        await feed.press(WizCb(step="mday", value="ok").pack())

    before = len(telegram.edits)
    await feed.press(WizCb(step=step, value=value).pack())

    assert len(telegram.edits) == before
    assert await reminders(session_factory) == []


@pytest.mark.parametrize(
    ("kind", "steps"),
    [
        (
            "weekly",
            [("wday", "1"), ("wday", "ok"), ("time", pack_wall_time("09:00")), ("times", "ok")],
        ),
        (
            "monthly",
            [
                ("mday", "1"),
                ("mday", "ok"),
                ("miss", "last"),
                ("time", pack_wall_time("09:00")),
                ("times", "ok"),
            ],
        ),
        ("interval", [("every", "60"), ("window", pack_window("09:00", "21:00"))]),
    ],
)
async def test_the_planner_materialises_what_the_new_kinds_create(
    session_factory, feed, telegram, fake_clock, context, kind, steps
):
    """The wizard and the worker have to agree about the first firing moment."""
    category_id = await seed_category(session_factory)
    await onboard(feed)

    await start_wizard(feed, category_id, "Что-нибудь")
    await feed.press(WizCb(step="kind", value=kind).pack())
    for step, value in steps:
        await feed.press(WizCb(step=step, value=value).pack())
    await feed.press(WizCb(step="confirm", value="yes").pack())

    async with session_factory() as session:
        # Wide enough for a monthly schedule to have somewhere to land: the
        # default 48-hour horizon never reaches the next first of the month.
        planner = PlanningService(
            session, fake_clock, horizon_hours=24 * 40, occurrence_ttl_minutes=180
        )
        first = await planner.materialize()
        # Replan the same window rather than the next one: a dense interval
        # schedule outruns one cycle, so a plain second call would legitimately
        # continue. What must not double is the window already written.
        await session.execute(sa.update(Reminder).values(planned_until=None))
        await session.commit()
        again = await planner.materialize()
        planned = list((await session.execute(sa.select(Occurrence))).scalars().all())

    assert first.occurrences_created > 0
    assert again.occurrences_created == 0, "replanning the same window must add nothing"
    assert len(planned) == first.occurrences_created
    assert len({occurrence.scheduled_for for occurrence in planned}) == len(planned)
