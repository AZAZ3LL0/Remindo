"""Reminder wizard screens. Handlers never build their own keyboards."""

from collections.abc import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.callbacks import WizCb, pack_wall_time
from app.bot.keyboards.pickers import (
    SELECTED_MARK,
    interval_picker_kb,
    monthday_picker_kb,
    time_picker_kb,
    weekday_picker_kb,
    window_picker_kb,
)
from app.bot.render.texts import DEFAULT_LANG, Lang, T
from app.domain.contracts import ScheduleKind

#: `WizCb.value` atoms that are commands rather than data. No preset may
#: collide with them; the contract test holds that line.
RESERVED_VALUES: frozenset[str] = frozenset({"today", "tmrw", "man", "ok", "last", "skip"})

#: Every schedule kind the wizard can build, which after S7 is every kind the
#: contract defines (tech.md 5).
WIZARD_SCHEDULE_KINDS: tuple[ScheduleKind, ...] = (
    ScheduleKind.ONCE,
    ScheduleKind.DAILY,
    ScheduleKind.WEEKLY,
    ScheduleKind.MONTHLY,
    ScheduleKind.INTERVAL,
)

#: `WizCb(step="miss")` atoms and the `on_missing_day` values they mean. The
#: atom is shorter than the field: 64 bytes are shared with prefix and step.
MISSING_DAY_ATOMS: dict[str, str] = {"last": "last_day", "skip": "skip"}

#: Wall-clock hours offered for a daily schedule. Anything else arrives as
#: manual input, so the list stays short instead of complete.
DAILY_TIME_PRESETS: tuple[str, ...] = (
    "07:00",
    "08:00",
    "09:00",
    "12:00",
    "15:00",
    "18:00",
    "20:00",
    "22:00",
)


def _cancel_button(lang: Lang) -> InlineKeyboardButton:
    """Shared cancel atom (tech.md 17.4). The wizard has no atom of its own."""
    return InlineKeyboardButton(
        text=T("btn.cancel", lang), callback_data=WizCb(step="confirm", value="no").pack()
    )


def _cancel(builder: InlineKeyboardBuilder, lang: Lang) -> None:
    builder.button(text=T("btn.cancel", lang), callback_data=WizCb(step="confirm", value="no"))


def schedule_kind_kb(lang: Lang = DEFAULT_LANG) -> InlineKeyboardMarkup:
    """One button per schedule kind the wizard knows how to build."""
    builder = InlineKeyboardBuilder()
    for kind in WIZARD_SCHEDULE_KINDS:
        builder.button(
            text=T(f"btn.kind_{kind.value}", lang),
            callback_data=WizCb(step="kind", value=kind.value),
        )
    builder.adjust(len(WIZARD_SCHEDULE_KINDS))

    footer = InlineKeyboardBuilder()
    _cancel(footer, lang)
    builder.attach(footer)
    return builder.as_markup()


def date_picker_kb(lang: Lang = DEFAULT_LANG) -> InlineKeyboardMarkup:
    """Today and tomorrow plus manual entry.

    Only two presets, because the keyboard is pure: naming a third day would
    mean reading a clock, and a keyboard never reads one.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text=T("btn.today", lang), callback_data=WizCb(step="date", value="today"))
    builder.button(text=T("btn.tomorrow", lang), callback_data=WizCb(step="date", value="tmrw"))
    builder.button(text=T("btn.manual_input", lang), callback_data=WizCb(step="date", value="man"))
    _cancel(builder, lang)
    builder.adjust(2, 2)
    return builder.as_markup()


def once_time_kb(lang: Lang = DEFAULT_LANG) -> InlineKeyboardMarkup:
    """Shared time presets (tech.md 9) with the wizard's cancel underneath."""
    builder = InlineKeyboardBuilder.from_markup(time_picker_kb("at", lang))
    builder.row(_cancel_button(lang))
    return builder.as_markup()


def daily_times_kb(selected: Sequence[str], lang: Lang = DEFAULT_LANG) -> InlineKeyboardMarkup:
    """Toggles: pressing a chosen time removes it, pressing a free one adds it."""
    chosen = set(selected)
    builder = InlineKeyboardBuilder()
    for value in DAILY_TIME_PRESETS:
        mark = SELECTED_MARK if value in chosen else ""
        builder.button(
            text=f"{mark}{value}",
            callback_data=WizCb(step="time", value=pack_wall_time(value)),
        )
    builder.adjust(4, 4)

    footer = InlineKeyboardBuilder()
    footer.button(text=T("btn.manual_input", lang), callback_data=WizCb(step="time", value="man"))
    footer.button(text=T("btn.ready", lang), callback_data=WizCb(step="times", value="ok"))
    _cancel(footer, lang)
    footer.adjust(2, 1)
    builder.attach(footer)
    return builder.as_markup()


def _with_cancel(keyboard: InlineKeyboardMarkup, lang: Lang) -> InlineKeyboardMarkup:
    """A shared picker (tech.md 9) with the wizard's cancel row underneath.

    Every wizard screen is cancellable (tech.md 19.3); a screen without it is a
    dead end the user leaves only by restarting.
    """
    builder = InlineKeyboardBuilder.from_markup(keyboard)
    builder.row(_cancel_button(lang))
    return builder.as_markup()


def weekly_days_kb(selected: Sequence[int], lang: Lang = DEFAULT_LANG) -> InlineKeyboardMarkup:
    """Weekday toggles (tech.md 9) plus cancel."""
    return _with_cancel(weekday_picker_kb(selected, lang), lang)


def monthday_kb(selected: Sequence[int], lang: Lang = DEFAULT_LANG) -> InlineKeyboardMarkup:
    """Day-of-month toggles (tech.md 9) plus cancel."""
    return _with_cancel(monthday_picker_kb(selected, lang), lang)


def interval_kb(lang: Lang = DEFAULT_LANG) -> InlineKeyboardMarkup:
    """Interval presets (tech.md 9) plus cancel.

    Manual entry already sits on the shared picker, and it now leads somewhere:
    the wizard reads a hand-typed step off the `every` step.
    """
    return _with_cancel(interval_picker_kb(lang), lang)


def window_kb(lang: Lang = DEFAULT_LANG) -> InlineKeyboardMarkup:
    """Window presets (tech.md 9) plus manual entry and cancel."""
    builder = InlineKeyboardBuilder.from_markup(window_picker_kb(lang))
    builder.row(
        InlineKeyboardButton(
            text=T("btn.manual_input", lang),
            callback_data=WizCb(step="window", value="man").pack(),
        )
    )
    builder.row(_cancel_button(lang))
    return builder.as_markup()


def missing_day_kb(lang: Lang = DEFAULT_LANG) -> InlineKeyboardMarkup:
    """What a monthly schedule does in a month without the chosen day."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=T("btn.missing_last_day", lang), callback_data=WizCb(step="miss", value="last")
    )
    builder.button(text=T("btn.missing_skip", lang), callback_data=WizCb(step="miss", value="skip"))
    _cancel(builder, lang)
    builder.adjust(2, 1)
    return builder.as_markup()
