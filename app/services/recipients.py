"""Recipient facts the queue services need, read off the user row."""

from zoneinfo import ZoneInfo

from app.db.models import User
from app.domain.quiet_hours import QuietHours


def quiet_hours_of(user: User) -> QuietHours:
    """The silence every delivery to this user must respect.

    The timezone comes from the user, never from `reminders.timezone`: that
    column is a snapshot taken when the reminder was created (tech.md 4.2), so
    a user who moved would be silenced against the wall clock of the city they
    left.
    """
    return QuietHours(tz=ZoneInfo(user.timezone), start=user.quiet_start, end=user.quiet_end)
