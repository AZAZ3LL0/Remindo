"""Settings screen text."""

from app.bot.render.texts import T
from app.db.models import User
from app.domain.schedules import format_hhmm


def format_quiet(user: User) -> str:
    if user.quiet_start is None or user.quiet_end is None:
        return T("settings.quiet_off", user.language)
    return T(
        "settings.quiet_value",
        user.language,
        start=format_hhmm(user.quiet_start),
        end=format_hhmm(user.quiet_end),
    )


def render_settings(user: User) -> str:
    return T(
        "settings.title",
        user.language,
        timezone=user.timezone,
        language=T(f"lang.{user.language}", user.language),
        quiet=format_quiet(user),
    )
