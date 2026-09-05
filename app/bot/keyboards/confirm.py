"""Yes / Cancel confirmation."""

from typing import Literal

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.callbacks import CatCb, RemCb, WizCb
from app.bot.render.texts import DEFAULT_LANG, Lang, T

ConfirmAction = Literal["delete", "create", "archive"]


def confirm_kb(
    action: ConfirmAction, entity_id: int, lang: Lang = DEFAULT_LANG
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if action == "delete":
        # Cancelling goes back where it came from. Deleting has a card to
        # return to, unlike creation and category archiving (tech.md 21.6).
        builder.button(
            text=T("btn.yes", lang),
            callback_data=RemCb(reminder_id=entity_id, action="confirm_delete"),
        )
        builder.button(
            text=T("btn.cancel", lang), callback_data=RemCb(reminder_id=entity_id, action="open")
        )
        builder.adjust(2)
        return builder.as_markup()
    if action == "archive":
        builder.button(
            text=T("btn.yes", lang),
            callback_data=CatCb(category_id=entity_id, action="confirm_archive"),
        )
    else:
        builder.button(text=T("btn.yes", lang), callback_data=WizCb(step="confirm", value="yes"))
    builder.button(text=T("btn.cancel", lang), callback_data=WizCb(step="confirm", value="no"))
    builder.adjust(2)
    return builder.as_markup()
