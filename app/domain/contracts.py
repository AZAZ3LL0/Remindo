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
    DIGEST_SEND = "digest.send"
    OPS_MONITOR = "ops.monitor"


class HealthStatus(StrEnum):
    """What the worker's healthcheck answers (tech.md 24.1).

    Two states, because the reader is a docker healthcheck with two outcomes:
    an intermediate warning would have nowhere to go.
    """

    OK = "ok"
    STALE = "stale"


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

#: Reminder limits mirrored from the schema (tech.md 4.2, 18.2), for the same
#: reason the category limits are mirrored: the domain rejects a value before
#: the database gets the chance to.
REMINDER_TITLE_MAX_LENGTH: Final = 120
REMINDER_NOTE_MAX_LENGTH: Final = 1000

#: Snooze step and automatic repeat, both in minutes (tech.md 21.5). A day is
#: the ceiling for the same reason it is for an interval (tech.md 19.2): the
#: values live in SMALLINT, and a step longer than a day is a wrong screen. The
#: repeat floor matches the interval floor: a repeat more frequent than a sweep
#: never happens anyway.
SNOOZE_MIN_MINUTES: Final = 1
SNOOZE_MAX_MINUTES: Final = 1440
REPEAT_MIN_MINUTES: Final = 5
REPEAT_MAX_MINUTES: Final = 1440

#: Invitation limits (tech.md 22.4). The token is base64url of
#: INVITE_TOKEN_BYTES without padding, so the two lengths are one fact stated
#: twice and the contract test holds them together: drifting apart, they would
#: produce a link the parser of tech.md 22.2 rejects.
INVITE_TOKEN_BYTES: Final = 16
INVITE_TOKEN_LENGTH: Final = 22
INVITE_TTL_HOURS: Final = 72

#: Watchers one reminder may carry, the owner not counted. Every acceptance
#: multiplies deliveries by one more per occurrence, so a link leaked into a
#: public chat would otherwise turn a reminder into a broadcast.
REMINDER_WATCHERS_MAX: Final = 10

#: Telegram's ceiling on a `?start=` payload, mirrored for the same reason the
#: category limits are (tech.md 17.2): the domain must refuse a value before
#: the transport truncates it silently.
DEEP_LINK_MAX_LENGTH: Final = 64

#: How far ahead the creation wizard accepts a date and looks for the first
#: firing moment (tech.md 18.2). A year with room for a leap day: anything
#: further out is almost always a typo, and the search stays bounded.
WIZARD_MAX_DAYS_AHEAD: Final = 366

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
