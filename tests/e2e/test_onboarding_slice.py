"""S1 end to end: update -> handler -> service -> db, through real routers.

Acceptance criteria of tech.md 15 (S1): /start creates the user and asks for a
timezone once, the zone can be picked or typed, language and quiet hours are
editable from /settings, and pressing the same button twice changes nothing.
"""

from datetime import time

import sqlalchemy as sa

from app.bot.callbacks import SetCb, WizCb, pack_wall_time
from app.db.models import User
from tests.e2e.conftest import TG_USER_ID


async def fetch_user(session_factory) -> User:
    async with session_factory() as session:
        stmt = sa.select(User).where(User.tg_user_id == TG_USER_ID)
        return (await session.execute(stmt)).scalars().one()


async def count_users(session_factory) -> int:
    async with session_factory() as session:
        return int((await session.execute(sa.select(sa.func.count()).select_from(User))).scalar_one())


def last_text(telegram) -> str:
    return telegram.requests[-1].text


def texts(telegram) -> str:
    """Everything the bot has said so far, for order-independent assertions."""
    return "\n".join(
        request.text for request in telegram.requests if getattr(request, "text", None)
    )


async def test_first_contact_creates_the_user_and_asks_for_a_timezone(
    session_factory, feed, telegram
):
    await feed.message("/start")

    user = await fetch_user(session_factory)
    assert user.language == "ru"
    assert user.onboarded_at is None
    assert "таймзоне" in texts(telegram)


async def test_an_unknown_zone_keeps_the_question_open(session_factory, feed, telegram):
    await feed.message("/start")
    await feed.message("Mars/Olympus")

    assert "Не знаю такую таймзону" in last_text(telegram)
    user = await fetch_user(session_factory)
    assert user.onboarded_at is None
    assert user.timezone == "Europe/Moscow"

    # The state survived the mistake, so the next attempt still counts.
    await feed.message("Asia/Tbilisi")

    user = await fetch_user(session_factory)
    assert user.timezone == "Asia/Tbilisi"
    assert user.onboarded_at is not None


async def test_manual_entry_is_offered_and_accepted(session_factory, feed, telegram):
    await feed.message("/start")
    await feed.press(SetCb(field="tz", value="manual").pack())

    assert "IANA" in last_text(telegram)

    await feed.message("Australia/Lord_Howe")

    assert (await fetch_user(session_factory)).timezone == "Australia/Lord_Howe"


async def test_a_picked_zone_finishes_onboarding_and_opens_settings(
    session_factory, feed, telegram
):
    await feed.message("/start")
    await feed.press(SetCb(field="tz", value="Asia/Yekaterinburg").pack())

    user = await fetch_user(session_factory)
    assert user.timezone == "Asia/Yekaterinburg"
    assert user.onboarded_at is not None
    assert "Настройки" in last_text(telegram)


async def test_a_second_start_greets_instead_of_asking_again(session_factory, feed, telegram):
    await feed.message("/start")
    await feed.press(SetCb(field="tz", value="Europe/Samara").pack())
    first = await fetch_user(session_factory)

    telegram.requests.clear()
    await feed.message("/start")

    again = await fetch_user(session_factory)
    assert again.onboarded_at == first.onboarded_at
    assert "С возвращением" in texts(telegram)
    assert "таймзоне" not in texts(telegram)
    assert await count_users(session_factory) == 1


async def test_settings_switches_the_language_and_repeating_it_changes_nothing(
    session_factory, feed, telegram
):
    await feed.message("/start")
    await feed.press(SetCb(field="tz", value="Europe/Moscow").pack())

    await feed.message("/settings")
    await feed.press(SetCb(field="menu", value="lang").pack())
    await feed.press(SetCb(field="lang", value="en").pack())

    assert (await fetch_user(session_factory)).language == "en"
    assert "Settings" in last_text(telegram)

    await feed.press(SetCb(field="lang", value="en").pack())

    assert (await fetch_user(session_factory)).language == "en"


async def test_quiet_hours_are_chosen_in_two_steps(session_factory, feed, telegram):
    await feed.message("/start")
    await feed.press(SetCb(field="tz", value="Europe/Moscow").pack())

    await feed.message("/settings")
    await feed.press(SetCb(field="menu", value="quiet").pack())
    await feed.press(SetCb(field="quiet", value="edit").pack())
    await feed.press(WizCb(step="qs", value=pack_wall_time("23:00")).pack())

    assert (await fetch_user(session_factory)).quiet_start is None, "nothing is stored yet"

    await feed.press(WizCb(step="qe", value=pack_wall_time("07:00")).pack())

    user = await fetch_user(session_factory)
    assert (user.quiet_start, user.quiet_end) == (time(23, 0), time(7, 0))
    assert "23:00-07:00" in last_text(telegram)


async def test_quiet_hours_accept_typed_times_and_reject_junk(session_factory, feed, telegram):
    await feed.message("/start")
    await feed.press(SetCb(field="tz", value="Europe/Moscow").pack())

    await feed.message("/settings")
    await feed.press(SetCb(field="menu", value="quiet").pack())
    await feed.press(SetCb(field="quiet", value="edit").pack())
    await feed.message("25:99")

    assert "Не понял время" in last_text(telegram)
    assert (await fetch_user(session_factory)).quiet_start is None

    await feed.message("22:30")
    await feed.message("06:45")

    user = await fetch_user(session_factory)
    assert (user.quiet_start, user.quiet_end) == (time(22, 30), time(6, 45))


async def test_equal_bounds_are_refused_at_the_last_step(session_factory, feed, telegram):
    await feed.message("/start")
    await feed.press(SetCb(field="tz", value="Europe/Moscow").pack())

    await feed.message("/settings")
    await feed.press(SetCb(field="menu", value="quiet").pack())
    await feed.press(SetCb(field="quiet", value="edit").pack())
    await feed.press(WizCb(step="qs", value=pack_wall_time("23:00")).pack())
    await feed.press(WizCb(step="qe", value=pack_wall_time("23:00")).pack())

    assert (await fetch_user(session_factory)).quiet_start is None
    assert "совпадают" in telegram.answers[-1].text


async def test_quiet_hours_are_switched_off_once(session_factory, feed, telegram):
    await feed.message("/start")
    await feed.press(SetCb(field="tz", value="Europe/Moscow").pack())

    await feed.message("/settings")
    await feed.press(SetCb(field="menu", value="quiet").pack())
    await feed.press(SetCb(field="quiet", value="edit").pack())
    await feed.press(WizCb(step="qs", value=pack_wall_time("23:00")).pack())
    await feed.press(WizCb(step="qe", value=pack_wall_time("07:00")).pack())

    await feed.press(SetCb(field="menu", value="quiet").pack())
    await feed.press(SetCb(field="quiet", value="off").pack())
    await feed.press(SetCb(field="menu", value="quiet").pack())
    await feed.press(SetCb(field="quiet", value="off").pack())

    user = await fetch_user(session_factory)
    assert (user.quiet_start, user.quiet_end) == (None, None)


async def test_the_timezone_is_editable_from_settings_without_reonboarding(
    session_factory, feed, telegram
):
    await feed.message("/start")
    await feed.press(SetCb(field="tz", value="Europe/Moscow").pack())
    onboarded_at = (await fetch_user(session_factory)).onboarded_at

    await feed.message("/settings")
    await feed.press(SetCb(field="menu", value="tz").pack())
    await feed.press(SetCb(field="tz", value="manual").pack())
    await feed.message("America/New_York")

    user = await fetch_user(session_factory)
    assert user.timezone == "America/New_York"
    assert user.onboarded_at == onboarded_at


async def test_a_broken_callback_reaches_the_user_as_a_message_not_a_traceback(
    session_factory, feed, telegram
):
    await feed.message("/start")
    await feed.press(SetCb(field="tz", value="Europe/Moscow").pack())

    await feed.press(SetCb(field="menu", value="nope").pack())

    assert telegram.answers[-1].text == "Что-то пошло не так. Попробуй ещё раз."
