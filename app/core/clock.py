"""Time access. Nothing else in the codebase may read the wall clock."""

from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime:
        """Return the current moment, timezone-aware, in UTC."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    """Deterministic clock. Lives in app code because dev fakes use it too."""

    def __init__(self, moment: datetime) -> None:
        if moment.tzinfo is None:
            raise ValueError("clock moment must be timezone-aware")
        self._moment = moment.astimezone(UTC)

    def now(self) -> datetime:
        return self._moment

    def advance(self, delta: timedelta) -> datetime:
        self._moment += delta
        return self._moment

    def set(self, moment: datetime) -> datetime:
        if moment.tzinfo is None:
            raise ValueError("clock moment must be timezone-aware")
        self._moment = moment.astimezone(UTC)
        return self._moment
