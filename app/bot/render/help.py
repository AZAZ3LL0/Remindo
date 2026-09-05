"""The help screen (tech.md 25.6)."""

from app.bot.commands import COMMANDS
from app.bot.render.texts import Lang, T


def render_help(lang: Lang) -> str:
    """What the bot does, its commands, and how the reaction buttons work.

    The table is glued on from `cmd.*` rather than formatted into the body, so
    a ninth command edits the command list alone.
    """
    rows = "\n".join(f"/{command} — {T(key, lang)}" for command, key in COMMANDS)
    return f"{T('help.screen', lang)}\n{rows}"
