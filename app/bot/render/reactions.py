"""What a reaction says: the callback answer and the message it closes."""

from typing import Final
from zoneinfo import ZoneInfo

from app.bot.render.reminder import format_local
from app.bot.render.texts import DEFAULT_LANG, Lang, T
from app.domain.contracts import ActionKind
from app.domain.reactions import RejectReason
from app.services.reactions import ReactionResult

_APPLIED_KEYS: Final[dict[ActionKind, str]] = {
    ActionKind.DONE: "react.done",
    ActionKind.SKIP: "react.skipped",
}

_REJECTED_KEYS: Final[dict[RejectReason, str]] = {
    RejectReason.ALREADY_HANDLED: "react.already",
    RejectReason.EXPIRED: "react.expired",
}

#: The answer goes under the reminder, never instead of it: the user keeps
#: seeing what they reacted to.
OUTCOME_SEPARATOR = "\n\n"


def render_outcome(result: ReactionResult, tz: ZoneInfo, lang: Lang = DEFAULT_LANG) -> str:
    """One line saying what the tap did, for both the toast and the message."""
    if result.reason is not None:
        # A reason is carried exactly when the tap changed nothing.
        return T(_REJECTED_KEYS[result.reason], lang)
    if result.kind is ActionKind.SNOOZE:
        return T("react.snoozed", lang, until=format_local(result.snoozed_until, tz, lang))
    return T(_APPLIED_KEYS[result.kind], lang)


def render_reacted_message(body: str, outcome: str) -> str:
    """The reminder with its answer under it. The caller drops the buttons."""
    if not body:
        return outcome
    return f"{body}{OUTCOME_SEPARATOR}{outcome}"
