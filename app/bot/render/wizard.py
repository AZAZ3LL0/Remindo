"""Text of the wizard's confirmation screen and of the daily time list."""

from collections.abc import Sequence
from datetime import datetime

from app.bot.render.texts import DEFAULT_LANG, Lang, T
from app.domain.schedules import (
    DailySchedule,
    IntervalSchedule,
    OnceSchedule,
    Schedule,
    format_hhmm,
)

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


def render_confirmation(title: str, schedule: Schedule, lang: Lang = DEFAULT_LANG) -> str:
    """One question per schedule kind, spelling out what is about to be created."""
    if isinstance(schedule, OnceSchedule):
        return T("wizard.confirm_once", lang, title=title, at=format_wall_datetime(schedule.at))
    if isinstance(schedule, DailySchedule):
        return T(
            "wizard.confirm_daily",
            lang,
            title=title,
            times=render_times([format_hhmm(value) for value in schedule.times], lang),
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
