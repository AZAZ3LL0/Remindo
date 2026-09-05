"""The permanent keyboard end to end (tech.md 26).

Acceptance criteria: the buttons are there without being asked for, a press
opens exactly what the command opens, navigation wins over the wizard's free
text, and a caption drawn before a language switch keeps working.
"""

import pytest
from aiogram.methods import SendMessage
from aiogram.types import ReplyKeyboardMarkup

from app.bot.callbacks import CatCb, SetCb
from app.bot.commands import MENU_BUTTONS
from app.bot.render.texts import T
from app.db.models import Category


def last_text(telegram) -> str:
    return telegram.requests[-1].text


def keyboards(telegram) -> list[ReplyKeyboardMarkup]:
    return [
        request.reply_markup
        for request in telegram.requests
        if isinstance(request, SendMessage)
        and isinstance(request.reply_markup, ReplyKeyboardMarkup)
    ]


def captions(markup: ReplyKeyboardMarkup) -> list[str]:
    return [button.text for row in markup.keyboard for button in row]


async def seed_category(session_factory) -> int:
    async with session_factory() as session:
        category = Category(owner_id=None, code="task", title="Задачи", emoji="📌", is_system=True)
        session.add(category)
        await session.commit()
        return category.id


async def onboard(feed) -> None:
    await feed.message("/start")
    await feed.press(SetCb(field="tz", value="Europe/Moscow").pack())


# --- the keyboard arrives without being asked for ---------------------------


async def test_onboarding_ends_with_the_keyboard_drawn(session_factory, feed, telegram):
    await onboard(feed)

    assert captions(keyboards(telegram)[-1]) == [T(key, "ru") for _, key in MENU_BUTTONS]


async def test_coming_back_redraws_the_keyboard(session_factory, feed, telegram):
    """Somebody who collapsed the menu, or joined before it existed, gets it
    back on the next `/start` rather than never."""
    await onboard(feed)
    before = len(keyboards(telegram))

    await feed.message("/start")

    assert len(keyboards(telegram)) == before + 1


# --- a press opens what the command opens -----------------------------------


@pytest.mark.parametrize(("command", "key"), MENU_BUTTONS)
async def test_a_caption_opens_the_same_screen_as_its_command(
    session_factory, feed, telegram, command, key
):
    await seed_category(session_factory)
    await onboard(feed)

    await feed.message(f"/{command}")
    by_command = last_text(telegram)
    await feed.message(T(key, "ru"))

    assert last_text(telegram) == by_command


# --- navigation beats free text ---------------------------------------------


async def test_a_caption_inside_the_wizard_navigates_instead_of_naming(
    session_factory, feed, telegram
):
    """The condition the router order exists for (tech.md 26.4). Pressed on the
    title step, a button used to become the title of a reminder."""
    category_id = await seed_category(session_factory)
    await onboard(feed)
    await feed.message("/new")
    await feed.press(CatCb(category_id=category_id, action="pick").pack())

    await feed.message(T("btn.menu_list", "ru"))

    assert T("list.empty", "ru") in last_text(telegram)


async def test_navigating_away_drops_the_wizard(session_factory, feed, telegram):
    """The state goes with the screen (tech.md 26.5): otherwise the next phrase
    typed becomes the title of a reminder the user already left."""
    category_id = await seed_category(session_factory)
    await onboard(feed)
    await feed.message("/new")
    await feed.press(CatCb(category_id=category_id, action="pick").pack())
    await feed.message(T("btn.menu_list", "ru"))

    await feed.message("молоко")

    assert T("help.unknown", "ru") in last_text(telegram)


async def test_a_command_typed_inside_the_wizard_opens_it(session_factory, feed, telegram):
    """`/list` on the title step used to name a reminder `/list`."""
    category_id = await seed_category(session_factory)
    await onboard(feed)
    await feed.message("/new")
    await feed.press(CatCb(category_id=category_id, action="pick").pack())

    await feed.message("/list")

    assert T("list.empty", "ru") in last_text(telegram)


async def test_free_text_still_reaches_the_wizard(session_factory, feed, telegram):
    """The guard rejects commands and captions, not ordinary answers: the step
    that takes a title must keep taking one."""
    category_id = await seed_category(session_factory)
    await onboard(feed)
    await feed.message("/new")
    await feed.press(CatCb(category_id=category_id, action="pick").pack())

    await feed.message("молоко")

    assert T("wizard.pick_kind", "ru") in last_text(telegram)


# --- a caption survives a language switch -----------------------------------


async def test_a_caption_of_the_previous_language_still_works(session_factory, feed, telegram):
    """The keyboard in the chat was drawn once, so after a switch the user is
    looking at the captions of the language they left (tech.md 26.3)."""
    await onboard(feed)
    await feed.message("/settings")
    await feed.press(SetCb(field="lang", value="en").pack())

    await feed.message(T("btn.menu_list", "ru"))

    assert T("list.empty", "en") in last_text(telegram)


async def test_the_keyboard_is_redrawn_in_the_new_language(session_factory, feed, telegram):
    await onboard(feed)
    await feed.message("/settings")

    await feed.press(SetCb(field="lang", value="en").pack())

    assert captions(keyboards(telegram)[-1]) == [T(key, "en") for _, key in MENU_BUTTONS]
