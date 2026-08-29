"""Status enums, job identifiers and payload versions.

Enums are append-only: values are never renamed or removed, because they are
materialised as native PostgreSQL enum types.
"""

from enum import StrEnum
from typing import Final

SCHEDULE_PAYLOAD_VERSION: Final = 1


class Language(StrEnum):
    """Interface language. Stored as TEXT, not as a native PostgreSQL enum."""

    RU = "ru"
    EN = "en"


class ReminderStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class ScheduleKind(StrEnum):
    ONCE = "once"
    INTERVAL = "interval"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class OccurrenceStatus(StrEnum):
    PENDING = "pending"
    DISPATCHING = "dispatching"
    SENT = "sent"
    DONE = "done"
    SKIPPED = "skipped"
    EXPIRED = "expired"
    FAILED = "failed"


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    DONE = "done"
    SKIPPED = "skipped"
    SNOOZED = "snoozed"
    FAILED = "failed"
    BLOCKED = "blocked"


class RecipientRole(StrEnum):
    OWNER = "owner"
    WATCHER = "watcher"


class ActionKind(StrEnum):
    DONE = "done"
    SNOOZE = "snooze"
    SKIP = "skip"
    AUTO_EXPIRE = "auto_expire"


class JobId(StrEnum):
    """Worker cycles. Each one is a contract with its own idempotency test."""

    PLANNER_MATERIALIZE = "planner.materialize"
    DISPATCHER_DELIVER = "dispatcher.deliver"
    REAPER_SWEEP = "reaper.sweep"


class ErrorClass(StrEnum):
    """Transport failure classes the retry policy knows about (tech.md 7.2).

    Domain code must not import aiogram, so gateway exceptions are mapped onto
    this enum at the gateway boundary.
    """

    RETRY_AFTER = "retry_after"
    FORBIDDEN = "forbidden"
    BAD_REQUEST = "bad_request"
    TRANSIENT = "transient"


#: Delivery reached a final state; further reactions are no-ops.
TERMINAL_DELIVERY_STATUSES: Final = frozenset(
    {
        DeliveryStatus.DONE,
        DeliveryStatus.SKIPPED,
        DeliveryStatus.FAILED,
        DeliveryStatus.BLOCKED,
    }
)

#: Occurrence reached a final state; the planner never revisits it.
TERMINAL_OCCURRENCE_STATUSES: Final = frozenset(
    {
        OccurrenceStatus.DONE,
        OccurrenceStatus.SKIPPED,
        OccurrenceStatus.EXPIRED,
        OccurrenceStatus.FAILED,
    }
)

#: Category limits mirrored from the schema (tech.md 4.2, 17.2). The domain
#: rejects a value before the database gets the chance to.
CATEGORY_TITLE_MAX_LENGTH: Final = 64
CATEGORY_CODE_PATTERN: Final = r"^[a-z0-9_]{2,32}$"
DEFAULT_CATEGORY_EMOJI: Final = "\U0001f514"

#: Timezones offered as buttons during onboarding. Any other zone arrives as
#: manual IANA input, so this list stays short instead of complete.
POPULAR_TIMEZONES: Final[tuple[str, ...]] = (
    "Europe/Kaliningrad",
    "Europe/Moscow",
    "Europe/Samara",
    "Asia/Yekaterinburg",
    "Asia/Novosibirsk",
    "Asia/Irkutsk",
    "Asia/Vladivostok",
    "Europe/Berlin",
)
