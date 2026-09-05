"""Invitation tokens and deep links (tech.md 22.2).

Derived from what S10 promises: a link is handed out, followed, and eventually
stops working. Every property here is a way that promise can be broken.
"""

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.contracts import (
    DEEP_LINK_MAX_LENGTH,
    INVITE_TOKEN_BYTES,
    INVITE_TOKEN_LENGTH,
    REMINDER_WATCHERS_MAX,
    RecipientRole,
)
from app.domain.errors import PermissionDeniedError, RecipientLimitError, ValidationError
from app.domain.sharing import (
    INVITE_DEEP_LINK_PREFIX,
    InviteState,
    build_invite_link,
    build_invite_payload,
    check_join,
    invite_state,
    new_invite_token,
    parse_invite_payload,
)

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)

#: What Telegram accepts in a `?start=` payload.
PAYLOAD_ALPHABET = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")

entropy = st.binary(min_size=INVITE_TOKEN_BYTES, max_size=INVITE_TOKEN_BYTES)
tokens = entropy.map(new_invite_token)


class TestToken:
    @given(entropy)
    def test_a_token_is_always_the_length_the_contract_names(self, raw):
        assert len(new_invite_token(raw)) == INVITE_TOKEN_LENGTH

    @given(entropy)
    def test_a_token_only_uses_characters_telegram_accepts(self, raw):
        """A character Telegram escapes is a link a chat client mangles."""
        assert set(new_invite_token(raw)) <= PAYLOAD_ALPHABET

    @given(entropy)
    def test_a_token_is_a_function_of_its_entropy_alone(self, raw):
        """No clock and no randomness inside, so a test can reproduce one."""
        assert new_invite_token(raw) == new_invite_token(raw)

    @given(st.binary(max_size=INVITE_TOKEN_BYTES - 1))
    def test_too_little_entropy_is_refused(self, raw):
        with pytest.raises(ValidationError):
            new_invite_token(raw)

    def test_two_tokens_from_different_entropy_differ(self):
        assert new_invite_token(b"\x00" * 16) != new_invite_token(b"\x01" * 16)


class TestPayload:
    @given(tokens)
    def test_a_payload_round_trips(self, token):
        assert parse_invite_payload(build_invite_payload(token)) == token

    @given(tokens)
    def test_a_payload_fits_the_telegram_limit(self, token):
        assert len(build_invite_payload(token)) <= DEEP_LINK_MAX_LENGTH

    @given(tokens)
    def test_a_payload_is_readable_inside_a_url(self, token):
        payload = build_invite_payload(token)
        assert set(payload) <= PAYLOAD_ALPHABET

    @pytest.mark.parametrize(
        "payload",
        [
            "",
            "start",
            "inv",
            "inv_",
            "inv_short",
            "inv_" + "a" * (INVITE_TOKEN_LENGTH + 1),
            "inv_" + "!" * INVITE_TOKEN_LENGTH,
            "INV_" + "a" * INVITE_TOKEN_LENGTH,
            " inv_" + "a" * INVITE_TOKEN_LENGTH,
        ],
    )
    def test_a_payload_that_is_not_an_invitation_is_refused(self, payload):
        with pytest.raises(ValidationError):
            parse_invite_payload(payload)

    @given(tokens)
    def test_the_prefix_is_split_off_by_length_not_by_separator(self, token):
        """The token alphabet contains `_` too, so searching for one would cut
        the token in the wrong place."""
        payload = build_invite_payload(token)
        assert payload.startswith(INVITE_DEEP_LINK_PREFIX)
        assert parse_invite_payload(payload) == payload[len(INVITE_DEEP_LINK_PREFIX) :]


class TestLink:
    @given(tokens)
    def test_a_link_carries_the_payload_the_parser_accepts(self, token):
        link = build_invite_link("reminder_bot", token)
        assert link.endswith(build_invite_payload(token))
        assert "t.me/reminder_bot?start=" in link

    def test_a_leading_at_is_not_part_of_the_username(self):
        assert build_invite_link("@bot", "a" * INVITE_TOKEN_LENGTH) == build_invite_link(
            "bot", "a" * INVITE_TOKEN_LENGTH
        )

    @pytest.mark.parametrize("username", ["", "   ", "@"])
    def test_a_missing_bot_name_is_refused_rather_than_guessed(self, username):
        """A link to no bot is worse than no link: it fails on a real user."""
        with pytest.raises(ValidationError):
            build_invite_link(username, "a" * INVITE_TOKEN_LENGTH)


class TestState:
    @given(st.integers(min_value=1, max_value=10_000))
    def test_a_future_expiry_with_no_revocation_is_live(self, minutes):
        assert invite_state(NOW + timedelta(minutes=minutes), None, NOW) is InviteState.LIVE

    @given(st.integers(min_value=0, max_value=10_000))
    def test_an_expiry_that_has_arrived_is_expired(self, minutes):
        """The boundary is inclusive: at `expires_at` the link is already dead."""
        assert invite_state(NOW - timedelta(minutes=minutes), None, NOW) is InviteState.EXPIRED

    @given(
        st.integers(min_value=-10_000, max_value=10_000),
        st.integers(min_value=-10_000, max_value=10_000),
    )
    def test_revocation_wins_over_the_clock(self, expiry, revoked):
        """The reason belongs to the owner, so an owner who took a link back is
        told that, not that it timed out."""
        assert (
            invite_state(NOW + timedelta(minutes=expiry), NOW + timedelta(minutes=revoked), NOW)
            is InviteState.REVOKED
        )


class TestJoining:
    def test_the_owner_is_refused_before_the_limit_is_consulted(self):
        with pytest.raises(PermissionDeniedError):
            check_join(RecipientRole.OWNER, watchers=REMINDER_WATCHERS_MAX, limit=0)

    @given(st.integers(min_value=0, max_value=100))
    def test_an_existing_watcher_is_always_let_back_in(self, watchers):
        """Following one's own link twice must not be refused as a newcomer."""
        check_join(RecipientRole.WATCHER, watchers=watchers, limit=REMINDER_WATCHERS_MAX)

    @given(st.integers(min_value=0, max_value=REMINDER_WATCHERS_MAX - 1))
    def test_a_newcomer_fits_while_there_is_room(self, watchers):
        check_join(None, watchers=watchers, limit=REMINDER_WATCHERS_MAX)

    @given(st.integers(min_value=REMINDER_WATCHERS_MAX, max_value=1000))
    def test_a_newcomer_is_refused_once_the_limit_is_reached(self, watchers):
        with pytest.raises(RecipientLimitError):
            check_join(None, watchers=watchers, limit=REMINDER_WATCHERS_MAX)
