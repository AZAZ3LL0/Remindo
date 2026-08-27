"""Reminder action keyboard: the only place reaction buttons are built."""

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.callbacks import ReactCb
from app.bot.render.texts import DEFAULT_LANG, Lang, T


def reminder_actions_kb(
    delivery_id: int, snooze_minutes: int, lang: Lang = DEFAULT_LANG
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=T("btn.done", lang), callback_data=ReactCb(delivery_id=delivery_id, action="done")
    )
    builder.button(
        text=T("btn.snooze", lang, minutes=snooze_minutes),
        callback_data=ReactCb(delivery_id=delivery_id, action="snooze"),
    )
    builder.button(
        text=T("btn.skip", lang), callback_data=ReactCb(delivery_id=delivery_id, action="skip")
    )
    builder.adjust(1, 2)
    return builder.as_markup()
