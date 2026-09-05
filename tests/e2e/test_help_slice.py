"""Help end to end: the first minute of a new user (tech.md 25).

Acceptance criteria: the bot can explain itself, it never answers with silence,
and the catch-all that guarantees the second one never steals the wizard's
input to do it.
"""

from aiogram.exceptions import TelegramBadRequest

from app.bot.callbacks import CatCb, SetCb
from app.bot.commands import COMMANDS, menu_for
from app.bot.main import publish_commands
from app.bot.render.texts import SUPPORTED_LANGS
from app.db.models import Category


def last_text(telegram) -> str:
    return telegram.requests[-1].text


def texts(telegram) -> str:
    return "\n".join(
        request.text for request in telegram.requests if getattr(request, "text", None)
    )


async def seed_category(session_factory) -> int:
    async with session_factory() as session:
        category = Category(owner_id=None, code="task", title="Задачи", emoji="📌", is_system=True)
        session.add(category)
        await session.commit()
        return category.id


async def onboard(feed) -> None:
    await feed.message("/start")
    await feed.press(SetCb(field="tz", value="Europe/Moscow").pack())


# --- /help ------------------------------------------------------------------


async def test_help_lists_every_command(feed, telegram):
    await onboard(feed)

    await feed.message("/help")

    assert all(f"/{command}" in last_text(telegram) for command, _ in COMMANDS)


async def test_onboarding_ends_on_the_help_screen_not_on_settings(feed, telegram):
    """Somebody who just named their timezone is done with settings and has
    not yet seen the product (tech.md 25.5)."""
    await onboard(feed)

    assert "/new" in last_text(telegram)
    assert "Таймзона сохранена" in texts(telegram)


# --- silence is not an answer ----------------------------------------------


async def test_unrecognised_text_is_answered_rather_than_ignored(feed, telegram):
    await onboard(feed)
    before = len(telegram.requests)

    await feed.message("привет, что ты умеешь")

    assert len(telegram.requests) > before
    assert "Не понял" in last_text(telegram)
    assert "/new" in last_text(telegram)


async def test_a_step_waiting_only_for_a_button_still_answers_text(feed, telegram):
    """The category step takes callbacks only, so text there used to vanish."""
    await onboard(feed)
    await feed.message("/new")
    before = len(telegram.requests)

    await feed.message("что-то невпопад")

    assert len(telegram.requests) > before
    assert "Не понял" in last_text(telegram)


# --- the regression that matters -------------------------------------------


async def test_the_catch_all_never_steals_the_wizard_input(feed, telegram, session_factory):
    """Registered last, so every state-filtered handler goes first. If this
    breaks, creating a reminder becomes impossible (tech.md 25.4)."""
    category_id = await seed_category(session_factory)
    await onboard(feed)
    await feed.message("/new")
    await feed.press(CatCb(category_id=category_id, action="pick").pack())

    await feed.message("Зарядка")

    assert "Не понял" not in last_text(telegram)
    # The title reached the wizard, so the wizard moved on to its next question
    # instead of the catch-all answering in its place.
    assert "Какое расписание?" in last_text(telegram)


async def test_a_command_is_never_treated_as_unknown_text(feed, telegram):
    await onboard(feed)

    for command, _ in COMMANDS:
        await feed.message(f"/{command}")
        assert "Не понял" not in last_text(telegram), command


# --- the command menu -------------------------------------------------------


async def test_the_menu_is_published_for_every_language(context, fake_bot):
    await publish_commands(context)

    assert set(fake_bot.commands) == set(SUPPORTED_LANGS)
    assert fake_bot.commands["ru"] == menu_for("ru")


async def test_publishing_the_menu_twice_leaves_one_menu(context, fake_bot):
    await publish_commands(context)
    await publish_commands(context)

    assert len(fake_bot.commands["ru"]) == len(COMMANDS)


async def test_a_refused_menu_does_not_stop_the_bot(context, fake_bot):
    """A bot that will not boot because a caption failed to update is worse
    than a bot with a stale caption (tech.md 25.3)."""
    for _ in SUPPORTED_LANGS:
        fake_bot.fail_next(TelegramBadRequest(method=None, message="nope"))

    await publish_commands(context)

    assert fake_bot.commands == {}


async def test_one_language_failing_does_not_cost_the_other_its_menu(context, fake_bot):
    """Publication is per language, so a refusal is not a shared fate."""
    fake_bot.fail_next(TelegramBadRequest(method=None, message="nope"))

    await publish_commands(context)

    assert set(fake_bot.commands) == set(SUPPORTED_LANGS[1:])
