"""Text of the wizard's confirmation screen and of the daily time list."""

from collections.abc import Sequence
from datetime import datetime, time

from app.bot.render.texts import DEFAULT_LANG, WEEKDAY_LABELS, Lang, T
from app.domain.schedules import (
    DailySchedule,
    IntervalSchedule,
    MonthlySchedule,
    OnceSchedule,
    Schedule,
    WeeklySchedule,
    format_hhmm,
)

#: `on_missing_day` values and the text keys that spell them out.
MISSING_DAY_KEYS = {"last_day": "missing.last_day", "skip": "missing.skip"}

#: Wall-clock moment of a `once` schedule. The year is spelled out because the
#: wizard accepts a date up to a year ahead, where `01.09` is ambiguous.
WALL_DATETIME_FORMAT = "%d.%m.%Y %H:%M"

TIME_SEPARATOR = ", "


def format_wall_datetime(moment: datetime) -> str:
    """Local wall-clock moment as the user picked it, not converted anywhere."""
    return moment.strftime(WALL_DATETIME_FORMAT)


def render_times(times: Sequence[str], lang: Lang = DEFAULT_LANG) -> str:
    """The daily list as it stands, or a word saying it is still empty."""
    if not times:
        return T("wizard.times_none", lang)
    return TIME_SEPARATOR.join(sorted(times))


def render_weekdays(weekdays: Sequence[int], lang: Lang = DEFAULT_LANG) -> str:
    """ISO weekday numbers as their local short names, or a word saying none."""
    if not weekdays:
        return T("wizard.weekdays_none", lang)
    labels = WEEKDAY_LABELS.get(lang, WEEKDAY_LABELS[DEFAULT_LANG])
    return TIME_SEPARATOR.join(labels[day - 1] for day in sorted(set(weekdays)))


def render_month_days(days: Sequence[int], lang: Lang = DEFAULT_LANG) -> str:
    """Days of the month as numbers, or a word saying none are chosen yet."""
    if not days:
        return T("wizard.mdays_none", lang)
    return TIME_SEPARATOR.join(str(day) for day in sorted(set(days)))


def render_confirmation(title: str, schedule: Schedule, lang: Lang = DEFAULT_LANG) -> str:
    """One question per schedule kind, spelling out what is about to be created."""
    if isinstance(schedule, OnceSchedule):
        return T("wizard.confirm_once", lang, title=title, at=format_wall_datetime(schedule.at))
    if isinstance(schedule, DailySchedule):
        return T(
            "wizard.confirm_daily",
            lang,
            title=title,
            times=_times(schedule.times, lang),
        )
    if isinstance(schedule, WeeklySchedule):
        return T(
            "wizard.confirm_weekly",
            lang,
            title=title,
            weekdays=render_weekdays(schedule.weekdays, lang),
            times=_times(schedule.times, lang),
        )
    if isinstance(schedule, MonthlySchedule):
        return T(
            "wizard.confirm_monthly",
            lang,
            title=title,
            days=render_month_days(schedule.days, lang),
            times=_times(schedule.times, lang),
            missing=T(MISSING_DAY_KEYS[schedule.on_missing_day], lang),
        )
    if isinstance(schedule, IntervalSchedule):
        return T(
            "wizard.confirm_interval",
            lang,
            title=title,
            every_minutes=schedule.every_minutes,
            window_start=format_hhmm(schedule.window_start),
            window_end=format_hhmm(schedule.window_end),
        )
    raise ValueError(f"no confirmation for schedule kind {schedule.kind!r}")


def _times(times: Sequence[time], lang: Lang) -> str:
    return render_times([format_hhmm(value) for value in times], lang)
