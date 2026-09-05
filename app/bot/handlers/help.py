"""/help, and the answer to anything the bot does not recognise."""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.bot.render.help import render_help
from app.bot.render.texts import T
from app.db.models import User

router = Router(name="help")


@router.message(Command("help"))
async def handle_help(message: Message, user: User) -> None:
    await message.answer(render_help(user.language))


@router.message()
async def handle_unknown(message: Message, user: User) -> None:
    """Anything that reached the last router was understood by nobody.

    This router is registered last, so every state-filtered handler has already
    had its turn and the wizard's input cannot land here (tech.md 25.4).
    Silence would read as a crash rather than as a misunderstanding.
    """
    await message.answer(f"{T('help.unknown', user.language)}\n\n{render_help(user.language)}")
