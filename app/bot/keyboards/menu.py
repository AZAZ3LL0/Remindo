"""The permanent main menu (tech.md 26.6).

The only reply keyboard of the product (tech.md 9). Every other screen stays
inline, and the worker never draws this one: it sends reminders, not menus.
"""

from aiogram.types import ReplyKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder

from app.bot.commands import MENU_BUTTONS
from app.bot.render.texts import DEFAULT_LANG, Lang, T


def main_menu_kb(lang: Lang = DEFAULT_LANG) -> ReplyKeyboardMarkup:
    """Eight buttons, two to a row, in the order of the command list.

    `is_persistent` matters: a keyboard the user once collapsed must not vanish
    for good. `one_time_keyboard` is refused for the same reason from the other
    side, since a menu that hides after the first press stops being permanent
    exactly when somebody starts using it.
    """
    builder = ReplyKeyboardBuilder()
    for _, key in MENU_BUTTONS:
        builder.button(text=T(key, lang))
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True, is_persistent=True)
