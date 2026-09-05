"""The command list. One source for the Telegram menu and the help screen.

The menu and the table in `/help` are one fact shown twice (tech.md 25.1).
Drifting apart they lie in both directions, so both are built from here.
"""

from typing import Final

from app.bot.render.texts import Lang, T
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


def menu_for(lang: Lang) -> tuple[BotCommandSpec, ...]:
    return tuple(
        BotCommandSpec(command=command, description=T(key, lang)) for command, key in COMMANDS
    )
