"""Filters shared by handlers.

`NOT_A_COMMAND` is built once from the command list, so a ninth command is kept
out of every free-text step by adding it in one place (tech.md 26.5).
"""

from typing import Final

from aiogram.filters import Command

from app.bot.commands import ALL_COMMAND_NAMES

#: Guards the text steps of every form. Without it a command typed inside the
#: wizard becomes the answer to the current question, and `/list` on the title
#: step names a reminder `/list`.
NOT_A_COMMAND: Final = ~Command(*ALL_COMMAND_NAMES)
