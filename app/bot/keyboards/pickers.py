"""Category, time and weekday pickers."""

from collections.abc import Sequence

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.callbacks import CatCb, PageCb, WizCb
from app.bot.render.texts import DEFAULT_LANG, WEEKDAY_LABELS, Lang, T
from app.db.models import Category

CATEGORY_PAGE_SIZE = 8

#: Interval presets in minutes, offered by the reminder wizard.
INTERVAL_PRESETS: tuple[int, ...] = (30, 60, 90, 120, 180, 240)

#: Day windows offered by the wizard as "HH:MM-HH:MM".
WINDOW_PRESETS: tuple[tuple[str, str], ...] = (
    ("08:00", "22:00"),
    ("09:00", "21:00"),
    ("10:00", "18:00"),
    ("00:00", "00:00"),
)


def category_picker_kb(
    categories: Sequence[Category], page: int, lang: Lang = DEFAULT_LANG
) -> InlineKeyboardMarkup:
    start = page * CATEGORY_PAGE_SIZE
    chunk = categories[start : start + CATEGORY_PAGE_SIZE]

    builder = InlineKeyboardBuilder()
    for category in chunk:
        builder.button(
            text=f"{category.emoji} {category.title}",
            callback_data=CatCb(category_id=category.id, action="pick"),
        )
    builder.adjust(2)

    footer = InlineKeyboardBuilder()
    if page > 0:
        footer.button(text=T("btn.prev", lang), callback_data=PageCb(scope="cat", page=page - 1))
    if start + CATEGORY_PAGE_SIZE < len(categories):
        footer.button(text=T("btn.next", lang), callback_data=PageCb(scope="cat", page=page + 1))
    footer.button(text=T("btn.new_category", lang), callback_data=WizCb(step="cat", value="new"))
    footer.adjust(3)
    builder.attach(footer)
    return builder.as_markup()


def interval_picker_kb(lang: Lang = DEFAULT_LANG) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for minutes in INTERVAL_PRESETS:
        builder.button(text=f"{minutes}", callback_data=WizCb(step="every", value=str(minutes)))
    builder.button(text=T("btn.manual_input", lang), callback_data=WizCb(step="every", value="man"))
    builder.adjust(3, 3, 1)
    return builder.as_markup()


def window_picker_kb(lang: Lang = DEFAULT_LANG) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for start, end in WINDOW_PRESETS:
        builder.button(
            text=f"{start}-{end}",
            callback_data=WizCb(step="window", value=f"{start}{end}".replace(":", "")),
        )
    builder.adjust(2)
    return builder.as_markup()


def time_picker_kb(step: str, lang: Lang = DEFAULT_LANG) -> InlineKeyboardMarkup:
    """Quick presets for a wall-clock time plus manual entry."""
    builder = InlineKeyboardBuilder()
    for hour in (7, 8, 9, 12, 15, 18, 20, 22):
        value = f"{hour:02d}:00"
        builder.button(text=value, callback_data=WizCb(step=step, value=value))
    builder.button(text=T("btn.manual_input", lang), callback_data=WizCb(step=step, value="man"))
    builder.adjust(4, 4, 1)
    return builder.as_markup()


def weekday_picker_kb(selected: Sequence[int], lang: Lang = DEFAULT_LANG) -> InlineKeyboardMarkup:
    labels = WEEKDAY_LABELS.get(lang, WEEKDAY_LABELS[DEFAULT_LANG])
    builder = InlineKeyboardBuilder()
    for iso_day, label in enumerate(labels, start=1):
        mark = "+" if iso_day in selected else ""
        builder.button(text=f"{mark}{label}", callback_data=WizCb(step="wday", value=str(iso_day)))
    builder.button(text=T("btn.ready", lang), callback_data=WizCb(step="wday", value="ok"))
    builder.adjust(4, 3, 1)
    return builder.as_markup()
