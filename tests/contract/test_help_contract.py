"""The command list is welded to the dispatcher (tech.md 25.1, 25.2).

The point of these tests is that the menu cannot advertise a command nobody
handles, and a command cannot be added without reaching the menu and the help
screen. They walk the real dispatcher rather than a copy of the list, because a
copy would agree with itself.
"""

from datetime import UTC, datetime

import pytest
from aiogram.filters import Command

from app.bot.commands import COMMANDS, MENU_EXEMPT_COMMANDS, menu_for
from app.bot.main import HANDLER_MODULES, build_dispatcher
from app.bot.render.help import render_help
from app.bot.render.texts import SUPPORTED_LANGS, TEXTS
from app.core.config import Settings
from app.core.di import AppContext
from app.domain.errors import ContractViolation
from app.gateways.bot_gateway import BotCommandSpec
from app.gateways.fakes import MAX_TEXT_LENGTH, FakeBotGateway, FakeClock, validate_commands


def registered_commands(context) -> set[str]:
    """Every command any handler in the real dispatcher answers to."""
    found: set[str] = set()
    for router in build_dispatcher(context).sub_routers:
        for handler in router.message.handlers:
            for flt in handler.filters or ():
                callback = getattr(flt, "callback", None)
                if isinstance(callback, Command):
                    found.update(str(name) for name in callback.commands)
    return found


@pytest.fixture(scope="module")
def dispatcher_commands() -> set[str]:
    """The dispatcher assembles without touching the database, so the wiring is
    checkable here rather than only in an end-to-end run.

    Handler routers are module singletons, so they are detached first, the same
    way the end-to-end fixture does it.
    """
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


# --- the list and the dispatcher agree -------------------------------------


def test_every_command_in_the_menu_has_a_handler(dispatcher_commands):
    """A menu offering something that does not exist is worse than no menu."""
    advertised = {command for command, _ in COMMANDS}

    assert advertised <= dispatcher_commands


def test_every_command_the_bot_answers_reaches_the_menu(dispatcher_commands):
    advertised = {command for command, _ in COMMANDS}

    assert dispatcher_commands - advertised == MENU_EXEMPT_COMMANDS


def test_the_exemption_is_a_real_command_not_a_leftover():
    """A name that stopped existing would silence the test above for good."""
    assert MENU_EXEMPT_COMMANDS
    assert MENU_EXEMPT_COMMANDS.isdisjoint({command for command, _ in COMMANDS})


def test_the_list_holds_no_duplicates_and_no_slashes():
    names = [command for command, _ in COMMANDS]

    assert len(names) == len(set(names))
    assert all(not name.startswith("/") for name in names)


def test_every_description_key_exists_in_the_catalogue():
    assert all(key in TEXTS for _, key in COMMANDS)


# --- the menu is a payload Telegram would accept ---------------------------


@pytest.mark.parametrize("lang", SUPPORTED_LANGS)
def test_the_menu_passes_the_gateway_contract_in_every_language(lang):
    validate_commands(menu_for(lang))


@pytest.mark.parametrize("lang", SUPPORTED_LANGS)
async def test_publishing_the_menu_records_it_under_its_language(lang):
    fake = FakeBotGateway()

    await fake.set_commands(menu_for(lang), lang)

    assert fake.commands[lang] == menu_for(lang)


async def test_publishing_twice_leaves_one_menu_per_language():
    """Telegram replaces rather than appends, and so does the fake."""
    fake = FakeBotGateway()

    await fake.set_commands(menu_for("ru"), "ru")
    await fake.set_commands(menu_for("ru"), "ru")

    assert list(fake.commands) == ["ru"]
    assert len(fake.commands["ru"]) == len(COMMANDS)


@pytest.mark.parametrize(
    "spec",
    [
        BotCommandSpec(command="/new", description="leading slash"),
        BotCommandSpec(command="New", description="upper case"),
        BotCommandSpec(command="a" * 33, description="too long"),
        BotCommandSpec(command="new", description=""),
        BotCommandSpec(command="new", description="x" * 257),
    ],
)
def test_a_menu_telegram_would_reject_fails_the_fake_first(spec):
    with pytest.raises(ContractViolation):
        validate_commands([spec])


def test_the_same_command_twice_is_refused():
    with pytest.raises(ContractViolation):
        validate_commands([BotCommandSpec("new", "one"), BotCommandSpec("new", "two")])


# --- the help screen --------------------------------------------------------


@pytest.mark.parametrize("lang", SUPPORTED_LANGS)
def test_the_help_screen_names_every_command_and_fits_one_message(lang):
    screen = render_help(lang)

    assert len(screen) <= MAX_TEXT_LENGTH
    assert all(f"/{command}" in screen for command, _ in COMMANDS)


@pytest.mark.parametrize("lang", SUPPORTED_LANGS)
def test_the_help_screen_uses_the_same_descriptions_as_the_menu(lang):
    """One fact shown twice must not become two facts (tech.md 25.1)."""
    screen = render_help(lang)

    assert all(spec.description in screen for spec in menu_for(lang))
