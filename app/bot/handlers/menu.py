"""The permanent keyboard: a press opens the screen its command opens.

This router is registered first, and that is a condition of correctness rather
than a preference (tech.md 26.4). A pressed button arrives as an ordinary text
message, indistinguishable from an answer to the wizard, so navigation has to
win over free text. Registered anywhere later, the wizard would swallow the
press and name a reminder `Статистика`.

The mirror of the catch-all in `help`, which is registered last for the opposite
reason: it must win over nobody.
"""

from collections.abc import Awaitable, Callable
from typing import Final

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.commands import main_menu_labels
from app.bot.handlers import categories, lists, reminders, settings, share, stats
from app.bot.handlers import help as help_handlers
from app.core.clock import Clock
from app.db.models import User

router = Router(name="menu")

Route = Callable[[Message, User, AsyncSession, Clock, FSMContext], Awaitable[None]]

#: A button calls the command's handler instead of repeating its body: a second
#: copy of the same logic would drift from the first, the way the menu and the
#: help screen would drift apart without one list (tech.md 26.5).
ROUTES: Final[dict[str, Route]] = {
    "new": lambda msg, user, session, clock, state: reminders.handle_new(
        msg, user, session, clock, state
    ),
    "today": lambda msg, user, session, clock, state: lists.handle_today(
        msg, user, session, clock, state
    ),
    "list": lambda msg, user, session, clock, state: lists.handle_list(
        msg, user, session, clock, state
    ),
    "categories": lambda msg, user, session, clock, state: categories.handle_categories(
        msg, user, session, clock, state
    ),
    "stats": lambda msg, user, session, clock, state: stats.handle_stats(
        msg, user, session, clock, state
    ),
    "shared": lambda msg, user, session, clock, state: share.handle_shared(
        msg, user, session, clock, state
    ),
    "settings": lambda msg, user, session, clock, state: settings.handle_settings(msg, user, state),
    "help": lambda msg, user, session, clock, state: help_handlers.handle_help(msg, user, state),
}


@router.message(F.text.in_(main_menu_labels()))
async def handle_button(
    message: Message,
    user: User,
    session: AsyncSession,
    clock: Clock,
    state: FSMContext,
) -> None:
    """The caption is matched across every locale (tech.md 26.3).

    The keyboard in the chat was drawn once, so somebody who switched language
    is still looking at the captions of the language they left.
    """
    await ROUTES[main_menu_labels()[message.text or ""]](message, user, session, clock, state)
