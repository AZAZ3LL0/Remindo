"""The command list. One source for the Telegram menu and the help screen.

The menu and the table in `/help` are one fact shown twice (tech.md 25.1).
Drifting apart they lie in both directions, so both are built from here.
"""

from typing import Final

from app.bot.render.texts import SUPPORTED_LANGS, Lang, T
from app.gateways.bot_gateway import BotCommandSpec

#: Order is the order the user sees, in the menu and in the help screen alike.
#: Creating something comes first, because that is what a new user came for.
COMMANDS: Final[tuple[tuple[str, str], ...]] = (
    ("new", "cmd.new"),
    ("list", "cmd.list"),
    ("today", "cmd.today"),
    ("categories", "cmd.categories"),
    ("stats", "cmd.stats"),
    ("shared", "cmd.shared"),
    ("settings", "cmd.settings"),
    ("help", "cmd.help"),
)

#: Telegram draws its own Start button, so a menu entry would only repeat it.
#: Named rather than forgotten: a command missing from the menu on purpose must
#: not look like one missing by oversight (tech.md 25.1).
MENU_EXEMPT_COMMANDS: Final[frozenset[str]] = frozenset({"start"})


#: The permanent keyboard is the third consumer of the list above (tech.md
#: 26.1), and it carries every command. `MENU_EXEMPT_COMMANDS` keeps `/start`
#: out of the Telegram menu, which draws its own Start button; a keyboard has
#: nothing there to duplicate. Captions live apart from the descriptions because
#: a menu row is wide and a button is narrow (tech.md 26.2).
MENU_BUTTONS: Final[tuple[tuple[str, str], ...]] = (
    ("new", "btn.menu_new"),
    ("today", "btn.menu_today"),
    ("list", "btn.menu_list"),
    ("categories", "btn.menu_categories"),
    ("stats", "btn.menu_stats"),
    ("shared", "btn.menu_shared"),
    ("settings", "btn.menu_settings"),
    ("help", "btn.menu_help"),
)

#: Every command the bot answers to, the menu and the exemption alike. The
#: free-text filter is built from this, so a ninth command starts being kept out
#: of the wizard's input without anyone remembering to add it (tech.md 26.5).
ALL_COMMAND_NAMES: Final[tuple[str, ...]] = tuple(
    dict.fromkeys([command for command, _ in COMMANDS] + sorted(MENU_EXEMPT_COMMANDS))
)


def menu_for(lang: Lang) -> tuple[BotCommandSpec, ...]:
    return tuple(
        BotCommandSpec(command=command, description=T(key, lang)) for command, key in COMMANDS
    )


def main_menu_labels() -> dict[str, str]:
    """Caption to command name, across every locale (tech.md 26.3).

    A reply keyboard is drawn in the chat once and stays there, so somebody who
    switched language is looking at the captions of the language they left.
    Matching the current locale alone would leave those buttons dead.
    """
    return {T(key, lang): command for command, key in MENU_BUTTONS for lang in SUPPORTED_LANGS}
