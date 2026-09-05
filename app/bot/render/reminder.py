"""Reminder card and the reminder message the dispatcher sends."""

from collections.abc import Sequence
from datetime import datetime, time
from zoneinfo import ZoneInfo

from app.bot.render.texts import DEFAULT_LANG, WEEKDAY_LABELS, Lang, T
from app.db.models import Category, Reminder
from app.domain.contracts import ReminderStatus
from app.domain.schedules import (
    DailySchedule,
    IntervalSchedule,
    MonthlySchedule,
    OnceSchedule,
    Schedule,
    WeeklySchedule,
    format_hhmm,
    parse_schedule,
)

_STATUS_KEYS = {
    ReminderStatus.ACTIVE: "status.active",
    ReminderStatus.PAUSED: "status.paused",
    ReminderStatus.ARCHIVED: "status.archived",
}

#: `on_missing_day` values and the text keys that spell them out (tech.md 19.4).
_MISSING_DAY_KEYS = {"last_day": "missing.last_day", "skip": "missing.skip"}

_SEPARATOR = ", "

#: Wall-clock moment of a `once` schedule, spelled out with the year: the card
#: outlives the wizard, and `01.09` alone stops being unambiguous.
_WALL_DATETIME_FORMAT = "%d.%m.%Y %H:%M"


def format_local(moment: datetime | None, tz: ZoneInfo, lang: Lang = DEFAULT_LANG) -> str:
    if moment is None:
        return T("reminder.no_next_fire", lang)
    return moment.astimezone(tz).strftime("%d.%m %H:%M")


def render_reminder_message(
    reminder: Reminder, category: Category, fire_at: datetime, tz: ZoneInfo, lang: Lang
) -> str:
    return T(
        "reminder.message",
        lang,
        emoji=category.emoji,
        title=reminder.title,
        time=format_local(fire_at, tz, lang),
    )


def render_schedule_summary(schedule: Schedule, lang: Lang = DEFAULT_LANG) -> str:
    """One line stating what the schedule does (tech.md 21.7)."""
    if isinstance(schedule, OnceSchedule):
        return T("schedule.once", lang, at=schedule.at.strftime(_WALL_DATETIME_FORMAT))
    if isinstance(schedule, DailySchedule):
        return T("schedule.daily", lang, times=_times(schedule.times))
    if isinstance(schedule, WeeklySchedule):
        return T(
            "schedule.weekly",
            lang,
            weekdays=_weekdays(schedule.weekdays, lang),
            times=_times(schedule.times),
        )
    if isinstance(schedule, MonthlySchedule):
        return T(
            "schedule.monthly",
            lang,
            days=_SEPARATOR.join(str(day) for day in schedule.days),
            times=_times(schedule.times),
            missing=T(_MISSING_DAY_KEYS[schedule.on_missing_day], lang),
        )
    if isinstance(schedule, IntervalSchedule):
        return T(
            "schedule.interval",
            lang,
            every_minutes=schedule.every_minutes,
            window_start=format_hhmm(schedule.window_start),
            window_end=format_hhmm(schedule.window_end),
        )
    raise ValueError(f"no summary for schedule kind {schedule.kind!r}")


def render_reminder_card(
    reminder: Reminder,
    category: Category,
    next_fire: datetime | None,
    tz: ZoneInfo,
    lang: Lang = DEFAULT_LANG,
    watchers: int = 0,
) -> str:
    """The card the user reads before deciding what to change (tech.md 21.7).

    `watchers` counts the recipients other than the owner. A reminder that goes
    out to three more people has to say so on the one screen where its state is
    read (tech.md 22.8).
    """
    repeat = (
        T("reminder.repeat_off", lang)
        if reminder.repeat_after_minutes is None
        else T("reminder.repeat_on", lang, minutes=reminder.repeat_after_minutes)
    )
    schedule = T(
        "reminder.schedule",
        lang,
        summary=render_schedule_summary(parse_schedule(reminder.schedule), lang),
        snooze=reminder.snooze_minutes,
        repeat=repeat,
    )
    return T(
        "reminder.card",
        lang,
        emoji=category.emoji,
        title=reminder.title,
        status=T(_STATUS_KEYS[reminder.status], lang),
        schedule=schedule,
        next_fire=format_local(next_fire, tz, lang),
        shared="" if watchers <= 0 else T("reminder.shared", lang, count=watchers),
        note="" if reminder.note is None else T("reminder.note", lang, note=reminder.note),
    )


def _times(times: Sequence[time]) -> str:
    return _SEPARATOR.join(format_hhmm(value) for value in times)


def _weekdays(weekdays: Sequence[int], lang: Lang) -> str:
    labels = WEEKDAY_LABELS.get(lang, WEEKDAY_LABELS[DEFAULT_LANG])
    return _SEPARATOR.join(labels[day - 1] for day in weekdays)
