"""/help, and the answer to anything the bot does not recognise."""

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot.keyboards.menu import main_menu_kb
from app.bot.render.help import render_help
from app.bot.render.texts import T
from app.db.models import User

router = Router(name="help")


@router.message(Command("help"))
async def handle_help(message: Message, user: User, state: FSMContext) -> None:
    # The help screen carries no inline keyboard, so it is one of the places
    # where the permanent menu can ride along (tech.md 26.6).
    await state.clear()
    await message.answer(render_help(user.language), reply_markup=main_menu_kb(user.language))


@router.message()
async def handle_unknown(message: Message, user: User) -> None:
    """Anything that reached the last router was understood by nobody.

    This router is registered last, so every state-filtered handler has already
    had its turn and the wizard's input cannot land here (tech.md 25.4).
    Silence would read as a crash rather than as a misunderstanding.

    The keyboard rides along because somebody who reached this line is lost, and
    they are the likeliest person to have lost the menu too.
    """
    await message.answer(
        f"{T('help.unknown', user.language)}\n\n{render_help(user.language)}",
        reply_markup=main_menu_kb(user.language),
    )
