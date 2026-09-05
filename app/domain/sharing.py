"""Invitation tokens and deep links (tech.md 22.2).

Pure by contract (tech.md 3): no clock, no IO, no randomness. `new_invite_token`
takes the entropy it needs the same way the pure functions take `now` from the
`Clock`, so a token is reproducible in a test without patching anything.
"""

import base64
import re
from datetime import datetime
from enum import StrEnum
from typing import Final

from app.domain.contracts import (
    DEEP_LINK_MAX_LENGTH,
    INVITE_TOKEN_LENGTH,
    REMINDER_WATCHERS_MAX,
    RecipientRole,
)
from app.domain.errors import (
    PermissionDeniedError,
    RecipientLimitError,
    ValidationError,
)

#: What marks a start payload as an invitation. Fixed length, so the payload is
#: split by a slice and never by searching for a separator: the token alphabet
#: contains `_` too.
INVITE_DEEP_LINK_PREFIX: Final = "inv_"

#: Telegram accepts `A-Za-z0-9_-` in a start payload; base64url is a subset.
_TOKEN_PATTERN: Final = re.compile(rf"^[A-Za-z0-9_-]{{{INVITE_TOKEN_LENGTH}}}$")

#: Where a deep link points. The bot name is the only variable part.
_LINK_TEMPLATE: Final = "https://t.me/{username}?start={payload}"


class InviteState(StrEnum):
    """What an invitation is worth right now."""

    LIVE = "live"
    EXPIRED = "expired"
    REVOKED = "revoked"


def new_invite_token(entropy: bytes) -> str:
    """Turn raw bytes into a token, deterministically.

    base64url without padding: `=` is not in Telegram's payload alphabet, and a
    token that needs escaping is a token that gets mangled by a chat client.
    """
    token = base64.urlsafe_b64encode(entropy).decode().rstrip("=")
    if not _TOKEN_PATTERN.match(token):
        raise ValidationError(f"entropy does not yield a {INVITE_TOKEN_LENGTH}-character token")
    return token


def build_invite_payload(token: str) -> str:
    """The `?start=` payload carrying one token."""
    payload = f"{INVITE_DEEP_LINK_PREFIX}{token}"
    if len(payload) > DEEP_LINK_MAX_LENGTH:
        raise ValidationError(f"deep link payload exceeds {DEEP_LINK_MAX_LENGTH} characters")
    return payload


def parse_invite_payload(raw: str) -> str:
    """The token inside a `?start=` payload.

    Anything else is a `ValidationError`, including an empty payload: `/start`
    without arguments is a different question and is answered elsewhere.
    """
    if not raw.startswith(INVITE_DEEP_LINK_PREFIX):
        raise ValidationError("payload is not an invitation")
    token = raw[len(INVITE_DEEP_LINK_PREFIX) :]
    if not _TOKEN_PATTERN.match(token):
        raise ValidationError("invitation token is malformed")
    return token


def build_invite_link(bot_username: str, token: str) -> str:
    """The link the owner hands out (tech.md 22.9)."""
    username = bot_username.lstrip("@").strip()
    if not username:
        raise ValidationError("bot username is not configured")
    return _LINK_TEMPLATE.format(username=username, payload=build_invite_payload(token))


def invite_state(expires_at: datetime, revoked_at: datetime | None, now: datetime) -> InviteState:
    """Whether an invitation still lets anybody in.

    Revocation wins over expiry: the reason belongs to the owner, not to the
    clock, and an owner who took a link back should be told so.
    """
    if revoked_at is not None:
        return InviteState.REVOKED
    if expires_at <= now:
        return InviteState.EXPIRED
    return InviteState.LIVE


def check_join(
    role: RecipientRole | None, watchers: int, limit: int = REMINDER_WATCHERS_MAX
) -> None:
    """Whether this user may still become a watcher of this reminder.

    The owner is refused before the limit is consulted: they are not a watcher
    and never count against it (tech.md 22.4).
    """
    if role is RecipientRole.OWNER:
        raise PermissionDeniedError("the owner already receives this reminder")
    if role is RecipientRole.WATCHER:
        return
    if watchers >= limit:
        raise RecipientLimitError(f"reminder already has {limit} watchers")
