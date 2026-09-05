"""The permanent keyboard is welded to the same command list (tech.md 26).

Acceptance criteria: the keyboard cannot offer a screen nobody opens, it cannot
quietly hide half the product, and a caption cannot stop working because the
user switched language. The dispatcher is walked for real rather than copied,
for the reason a copy would agree with itself.
"""

from datetime import UTC, datetime

import pytest

from app.bot.commands import (
    COMMANDS,
    MENU_BUTTONS,
    MENU_EXEMPT_COMMANDS,
    main_menu_labels,
)
from app.bot.handlers.menu import ROUTES
from app.bot.keyboards.menu import main_menu_kb
from app.bot.main import HANDLER_MODULES
from app.bot.render.texts import SUPPORTED_LANGS, TEXTS, T
from app.core.config import Settings
from app.core.di import AppContext
from app.gateways.fakes import FakeBotGateway, FakeClock
from tests.contract.test_help_contract import registered_commands


@pytest.fixture(scope="module")
def dispatcher_commands() -> set[str]:
    for module in HANDLER_MODULES:
        module.router._parent_router = None
    context = AppContext(
        settings=Settings(),
        engine=None,  # type: ignore[arg-type]
        session_factory=None,  # type: ignore[arg-type]
        clock=FakeClock(datetime(2026, 6, 1, tzinfo=UTC)),
        gateway=FakeBotGateway(),
        bot=None,
    )
    return registered_commands(context)


# --- the keyboard and the command list agree --------------------------------


def test_every_button_has_a_handler(dispatcher_commands):
    """A button opening nothing is worse than a missing button."""
    assert {command for command, _ in MENU_BUTTONS} <= dispatcher_commands


def test_every_command_reaches_the_keyboard():
    """The keyboard takes the whole list: `/start` is exempt from the Telegram
    menu, which draws its own Start button, and not from this one (tech.md 26.1).
    """
    assert {command for command, _ in MENU_BUTTONS} == {command for command, _ in COMMANDS}
    assert "start" in MENU_EXEMPT_COMMANDS


def test_every_button_is_routed():
    assert set(ROUTES) == {command for command, _ in MENU_BUTTONS}


def test_every_caption_key_exists_in_the_catalogue():
    assert all(key in TEXTS for _, key in MENU_BUTTONS)


def test_captions_carry_no_placeholders():
    """A caption is matched back to its command by comparing strings, so a value
    substituted into it would make the button unrecognisable (tech.md 26.7)."""
    assert all("{" not in T(key, lang) for _, key in MENU_BUTTONS for lang in SUPPORTED_LANGS)


# --- a caption survives a language switch -----------------------------------


def test_the_index_covers_every_locale():
    """The keyboard is drawn in the chat once and stays there, so somebody who
    switched language presses a caption of the language they left (tech.md 26.3).
    """
    labels = main_menu_labels()

    assert len(labels) == len(MENU_BUTTONS) * len(SUPPORTED_LANGS)
    for lang in SUPPORTED_LANGS:
        assert all(labels[T(key, lang)] == command for command, key in MENU_BUTTONS)


def test_captions_are_unique_across_locales():
    """Two commands sharing a caption would give a button leading anywhere."""
    captions = [T(key, lang) for _, key in MENU_BUTTONS for lang in SUPPORTED_LANGS]

    assert len(captions) == len(set(captions))


# --- the markup Telegram is handed ------------------------------------------


@pytest.mark.parametrize("lang", SUPPORTED_LANGS)
def test_the_keyboard_holds_every_caption_two_to_a_row(lang):
    keyboard = main_menu_kb(lang).keyboard

    assert [len(row) for row in keyboard] == [2] * (len(MENU_BUTTONS) // 2)
    assert [button.text for row in keyboard for button in row] == [
        T(key, lang) for _, key in MENU_BUTTONS
    ]


@pytest.mark.parametrize("lang", SUPPORTED_LANGS)
def test_the_keyboard_is_permanent(lang):
    """A keyboard collapsed once must come back, and one that hides after the
    first press stops being a menu exactly when it starts being used."""
    markup = main_menu_kb(lang)

    assert markup.is_persistent is True
    assert markup.resize_keyboard is True
    assert not markup.one_time_keyboard


def test_the_menu_router_is_consulted_first():
    """The condition the whole slice rests on (tech.md 26.4). A press arrives as
    plain text, so registered anywhere later the wizard would take it for an
    answer. The catch-all holds the same invariant from the other end.
    """
    names = [module.router.name for module in HANDLER_MODULES]

    assert names[0] == "menu"
    assert names[-2:] == ["help", "errors"]


def test_the_keyboard_carries_no_buttons_that_ask_for_data():
    """A menu button sends its caption and nothing else: contact, location and
    poll requests would arrive as messages the label index cannot resolve."""
    buttons = [button for row in main_menu_kb("ru").keyboard for button in row]

    assert all(
        button.request_contact is None
        and button.request_location is None
        and button.request_poll is None
        for button in buttons
    )
