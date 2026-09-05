"""Acceptance criteria of S10 against a real database (tech.md 15, 22).

What a user is promised: a link can be handed out and taken back, accepting one
starts the reminder arriving, and unsubscribing stops it. Every test below is
one of those promises, not a walk through the implementation.
"""

from datetime import timedelta

import pytest
import sqlalchemy as sa

from app.db.models import Delivery, Occurrence, ReminderInvite, ReminderRecipient, User
from app.domain.contracts import (
    REMINDER_WATCHERS_MAX,
    DeliveryStatus,
    OccurrenceStatus,
    RecipientRole,
)
from app.domain.errors import (
    InviteExpiredError,
    NotFoundError,
    PermissionDeniedError,
    RecipientLimitError,
)
from app.domain.sharing import InviteState, invite_state
from app.services.planning import PlanningService
from app.services.sharing import SharingService
from tests.conftest import FROZEN_NOW


def service(session, clock) -> SharingService:
    return SharingService(session, clock)


async def deliveries_of(session, reminder_id: int, user_id: int) -> list[Delivery]:
    stmt = (
        sa.select(Delivery)
        .join(Occurrence, Occurrence.id == Delivery.occurrence_id)
        .where(Occurrence.reminder_id == reminder_id, Delivery.user_id == user_id)
        .order_by(Delivery.id)
    )
    return list((await session.execute(stmt)).scalars().all())


async def recipient_of(session, reminder_id: int, user_id: int) -> ReminderRecipient | None:
    stmt = sa.select(ReminderRecipient).where(
        ReminderRecipient.reminder_id == reminder_id,
        ReminderRecipient.user_id == user_id,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def invites_of(session, reminder_id: int) -> list[ReminderInvite]:
    stmt = (
        sa.select(ReminderInvite)
        .where(ReminderInvite.reminder_id == reminder_id)
        .order_by(ReminderInvite.id)
    )
    return list((await session.execute(stmt)).scalars().all())


class TestIssuingALink:
    async def test_an_owner_gets_a_link_that_can_be_followed(
        self, db_session, fake_clock, reminder_factory
    ):
        reminder = await reminder_factory()
        invite = await service(db_session, fake_clock).issue_invite(reminder.owner_id, reminder.id)

        assert invite.expires_at > fake_clock.now()
        assert (
            invite_state(invite.expires_at, invite.revoked_at, fake_clock.now()) is InviteState.LIVE
        )

    async def test_a_new_link_takes_the_previous_one_back(
        self, db_session, fake_clock, reminder_factory
    ):
        """Two live links would mean revoking one revokes nothing (tech.md 22.1)."""
        reminder = await reminder_factory()
        sharing = service(db_session, fake_clock)
        first = await sharing.issue_invite(reminder.owner_id, reminder.id)
        second = await sharing.issue_invite(reminder.owner_id, reminder.id)

        rows = await invites_of(db_session, reminder.id)
        assert [row.id for row in rows] == [first.id, second.id]
        assert first.revoked_at is not None
        assert second.revoked_at is None
        assert first.token != second.token

    async def test_revoking_twice_revokes_once(self, db_session, fake_clock, reminder_factory):
        """Idempotency (tech.md 10): the second press has nothing left to take."""
        reminder = await reminder_factory()
        sharing = service(db_session, fake_clock)
        invite = await sharing.issue_invite(reminder.owner_id, reminder.id)

        assert await sharing.revoke_invite(reminder.owner_id, reminder.id) is True
        revoked_at = (await invites_of(db_session, reminder.id))[0].revoked_at
        fake_clock.advance(timedelta(minutes=5))
        assert await sharing.revoke_invite(reminder.owner_id, reminder.id) is False

        rows = await invites_of(db_session, reminder.id)
        assert len(rows) == 1
        assert rows[0].id == invite.id
        assert rows[0].revoked_at == revoked_at

    async def test_a_stranger_cannot_hand_out_a_link_to_somebody_elses_reminder(
        self, db_session, fake_clock, reminder_factory, user_factory
    ):
        reminder = await reminder_factory()
        stranger = await user_factory()
        with pytest.raises(PermissionDeniedError):
            await service(db_session, fake_clock).issue_invite(stranger.id, reminder.id)

    async def test_a_reminder_nobody_shared_has_no_live_link(
        self, db_session, fake_clock, reminder_factory
    ):
        """The access screen draws no revoke button in this state (tech.md 22.7)."""
        reminder = await reminder_factory()
        assert (
            await service(db_session, fake_clock).live_invite(reminder.owner_id, reminder.id)
            is None
        )

    async def test_an_expired_link_is_no_longer_the_live_one(
        self, db_session, fake_clock, reminder_factory
    ):
        reminder = await reminder_factory()
        sharing = service(db_session, fake_clock)
        await sharing.issue_invite(reminder.owner_id, reminder.id)

        fake_clock.advance(timedelta(days=4))
        assert await sharing.live_invite(reminder.owner_id, reminder.id) is None


class TestFollowingALink:
    async def test_following_a_link_leaves_a_pending_recipient(
        self, db_session, fake_clock, reminder_factory, user_factory
    ):
        """The row is what survives onboarding (tech.md 22.5)."""
        reminder = await reminder_factory()
        friend = await user_factory()
        sharing = service(db_session, fake_clock)
        invite = await sharing.issue_invite(reminder.owner_id, reminder.id)

        opened, owner = await sharing.open_invite(invite.token, friend)

        row = await recipient_of(db_session, reminder.id, friend.id)
        assert opened.id == reminder.id
        assert owner.id == reminder.owner_id
        assert row is not None
        assert row.role is RecipientRole.WATCHER
        assert row.accepted_at is None

    async def test_following_the_same_link_twice_leaves_one_row(
        self, db_session, fake_clock, reminder_factory, user_factory
    ):
        """Idempotency (tech.md 10): a link opened twice is still one invitation."""
        reminder = await reminder_factory()
        friend = await user_factory()
        sharing = service(db_session, fake_clock)
        invite = await sharing.issue_invite(reminder.owner_id, reminder.id)

        await sharing.open_invite(invite.token, friend)
        await sharing.open_invite(invite.token, friend)

        stmt = sa.select(sa.func.count()).where(
            ReminderRecipient.reminder_id == reminder.id,
            ReminderRecipient.user_id == friend.id,
        )
        assert int((await db_session.execute(stmt)).scalar_one()) == 1

    async def test_an_unknown_token_is_not_found(self, db_session, fake_clock, user_factory):
        friend = await user_factory()
        with pytest.raises(NotFoundError):
            await service(db_session, fake_clock).open_invite("a" * 22, friend)

    async def test_a_revoked_link_lets_nobody_in(
        self, db_session, fake_clock, reminder_factory, user_factory
    ):
        reminder = await reminder_factory()
        friend = await user_factory()
        sharing = service(db_session, fake_clock)
        invite = await sharing.issue_invite(reminder.owner_id, reminder.id)
        await sharing.revoke_invite(reminder.owner_id, reminder.id)

        with pytest.raises(InviteExpiredError):
            await sharing.open_invite(invite.token, friend)

    async def test_an_expired_link_lets_nobody_in(
        self, db_session, fake_clock, reminder_factory, user_factory
    ):
        reminder = await reminder_factory()
        friend = await user_factory()
        sharing = service(db_session, fake_clock)
        invite = await sharing.issue_invite(reminder.owner_id, reminder.id)

        fake_clock.advance(timedelta(days=4))
        with pytest.raises(InviteExpiredError):
            await sharing.open_invite(invite.token, friend)

    async def test_the_owner_cannot_join_their_own_reminder(
        self, db_session, fake_clock, reminder_factory
    ):
        reminder = await reminder_factory()
        owner = await db_session.get(User, reminder.owner_id)
        sharing = service(db_session, fake_clock)
        invite = await sharing.issue_invite(reminder.owner_id, reminder.id)

        with pytest.raises(PermissionDeniedError):
            await sharing.open_invite(invite.token, owner)

    async def test_a_full_reminder_takes_nobody_else(
        self, db_session, fake_clock, reminder_factory, user_factory
    ):
        """A link in a public chat must not turn one reminder into a broadcast."""
        reminder = await reminder_factory()
        sharing = service(db_session, fake_clock)
        invite = await sharing.issue_invite(reminder.owner_id, reminder.id)
        for _ in range(REMINDER_WATCHERS_MAX):
            await sharing.open_invite(invite.token, await user_factory())

        with pytest.raises(RecipientLimitError):
            await sharing.open_invite(invite.token, await user_factory())


class TestAccepting:
    async def test_accepting_catches_up_on_what_is_already_queued(
        self, db_session, fake_clock, reminder_factory, user_factory, occurrence_factory
    ):
        """The planner queued before the watcher arrived (tech.md 22.6)."""
        reminder = await reminder_factory()
        friend = await user_factory()
        ahead = await occurrence_factory(reminder, FROZEN_NOW + timedelta(hours=1))
        await occurrence_factory(reminder, FROZEN_NOW + timedelta(hours=3))
        sharing = service(db_session, fake_clock)
        invite = await sharing.issue_invite(reminder.owner_id, reminder.id)
        await sharing.open_invite(invite.token, friend)

        await sharing.accept(friend.id, reminder.id)

        rows = await deliveries_of(db_session, reminder.id, friend.id)
        assert len(rows) == 2
        assert {row.next_attempt_at for row in rows} >= {ahead.fire_at}
        assert all(row.status is DeliveryStatus.PENDING for row in rows)

    async def test_a_moment_that_has_already_passed_is_not_backfilled(
        self, db_session, fake_clock, reminder_factory, user_factory, occurrence_factory
    ):
        """A watcher who joined a minute ago is not told about a due moment
        they were not there for (tech.md 22.6)."""
        reminder = await reminder_factory()
        friend = await user_factory()
        await occurrence_factory(reminder, FROZEN_NOW - timedelta(hours=1))
        await occurrence_factory(reminder, FROZEN_NOW + timedelta(hours=1))
        sharing = service(db_session, fake_clock)
        invite = await sharing.issue_invite(reminder.owner_id, reminder.id)
        await sharing.open_invite(invite.token, friend)

        await sharing.accept(friend.id, reminder.id)

        rows = await deliveries_of(db_session, reminder.id, friend.id)
        assert [row.next_attempt_at for row in rows] == [FROZEN_NOW + timedelta(hours=1)]

    async def test_accepting_twice_creates_one_set_of_deliveries(
        self, db_session, fake_clock, reminder_factory, user_factory, occurrence_factory
    ):
        """Idempotency (tech.md 10): the second press changes nothing at all."""
        reminder = await reminder_factory()
        friend = await user_factory()
        await occurrence_factory(reminder, FROZEN_NOW + timedelta(hours=1))
        sharing = service(db_session, fake_clock)
        invite = await sharing.issue_invite(reminder.owner_id, reminder.id)
        await sharing.open_invite(invite.token, friend)

        await sharing.accept(friend.id, reminder.id)
        accepted_at = (await recipient_of(db_session, reminder.id, friend.id)).accepted_at
        fake_clock.advance(timedelta(minutes=5))
        await sharing.accept(friend.id, reminder.id)

        assert len(await deliveries_of(db_session, reminder.id, friend.id)) == 1
        assert (await recipient_of(db_session, reminder.id, friend.id)).accepted_at == accepted_at

    async def test_the_planner_then_delivers_to_both(
        self, db_session, fake_clock, reminder_factory, user_factory
    ):
        """The promise of S10: an accepted reminder reaches everyone who took it."""
        reminder = await reminder_factory()
        friend = await user_factory()
        sharing = service(db_session, fake_clock)
        invite = await sharing.issue_invite(reminder.owner_id, reminder.id)
        await sharing.open_invite(invite.token, friend)
        await sharing.accept(friend.id, reminder.id)

        await PlanningService(db_session, fake_clock, 48, 180).materialize()

        stmt = (
            sa.select(Delivery.user_id)
            .join(Occurrence, Occurrence.id == Delivery.occurrence_id)
            .where(Occurrence.reminder_id == reminder.id)
        )
        recipients = set((await db_session.execute(stmt)).scalars().all())
        assert recipients == {reminder.owner_id, friend.id}

    async def test_a_reminder_nobody_accepted_reaches_only_its_owner(
        self, db_session, fake_clock, reminder_factory, user_factory
    ):
        """A pending invitation is not a recipient (tech.md 7.1)."""
        reminder = await reminder_factory()
        friend = await user_factory()
        sharing = service(db_session, fake_clock)
        invite = await sharing.issue_invite(reminder.owner_id, reminder.id)
        await sharing.open_invite(invite.token, friend)

        await PlanningService(db_session, fake_clock, 48, 180).materialize()

        assert await deliveries_of(db_session, reminder.id, friend.id) == []

    async def test_declining_leaves_no_trace(
        self, db_session, fake_clock, reminder_factory, user_factory
    ):
        reminder = await reminder_factory()
        friend = await user_factory()
        sharing = service(db_session, fake_clock)
        invite = await sharing.issue_invite(reminder.owner_id, reminder.id)
        await sharing.open_invite(invite.token, friend)

        await sharing.decline(friend.id, reminder.id)

        assert await recipient_of(db_session, reminder.id, friend.id) is None


class TestLeaving:
    async def test_leaving_takes_back_what_has_not_gone_out(
        self, db_session, fake_clock, reminder_factory, user_factory, occurrence_factory
    ):
        reminder = await reminder_factory()
        friend = await user_factory()
        sharing = service(db_session, fake_clock)
        invite = await sharing.issue_invite(reminder.owner_id, reminder.id)
        await sharing.open_invite(invite.token, friend)
        await occurrence_factory(reminder, FROZEN_NOW + timedelta(hours=1))
        await sharing.accept(friend.id, reminder.id)

        await sharing.leave(friend.id, reminder.id)

        assert await deliveries_of(db_session, reminder.id, friend.id) == []
        assert await recipient_of(db_session, reminder.id, friend.id) is None

    async def test_leaving_does_not_take_away_a_message_already_on_screen(
        self,
        db_session,
        fake_clock,
        reminder_factory,
        user_factory,
        occurrence_factory,
        delivery_factory,
    ):
        """Live buttons belong to the recipient, not to the queue (tech.md 22.6)."""
        reminder = await reminder_factory()
        friend = await user_factory()
        sharing = service(db_session, fake_clock)
        invite = await sharing.issue_invite(reminder.owner_id, reminder.id)
        await sharing.open_invite(invite.token, friend)
        await sharing.accept(friend.id, reminder.id)

        occurrence = await occurrence_factory(reminder, FROZEN_NOW + timedelta(hours=1))
        sent = await delivery_factory(occurrence, friend.id, status=DeliveryStatus.SENT)
        snoozed = await delivery_factory(
            await occurrence_factory(reminder, FROZEN_NOW + timedelta(hours=2)),
            friend.id,
            status=DeliveryStatus.SNOOZED,
        )
        await db_session.commit()

        await sharing.leave(friend.id, reminder.id)

        kept = {row.id for row in await deliveries_of(db_session, reminder.id, friend.id)}
        assert kept == {sent.id, snoozed.id}

    async def test_leaving_leaves_the_other_recipients_alone(
        self,
        db_session,
        fake_clock,
        reminder_factory,
        user_factory,
        occurrence_factory,
    ):
        reminder = await reminder_factory()
        friend = await user_factory()
        sharing = service(db_session, fake_clock)
        invite = await sharing.issue_invite(reminder.owner_id, reminder.id)
        await sharing.open_invite(invite.token, friend)
        await occurrence_factory(reminder, FROZEN_NOW + timedelta(hours=1))
        await sharing.accept(friend.id, reminder.id)
        await PlanningService(db_session, fake_clock, 48, 180).materialize()

        await sharing.leave(friend.id, reminder.id)

        assert await deliveries_of(db_session, reminder.id, reminder.owner_id) != []
        assert await recipient_of(db_session, reminder.id, reminder.owner_id) is not None

    async def test_leaving_twice_drops_the_same_rows_once(
        self, db_session, fake_clock, reminder_factory, user_factory, occurrence_factory
    ):
        """Idempotency (tech.md 10): the second press has nothing to take back."""
        reminder = await reminder_factory()
        friend = await user_factory()
        sharing = service(db_session, fake_clock)
        invite = await sharing.issue_invite(reminder.owner_id, reminder.id)
        await sharing.open_invite(invite.token, friend)
        await occurrence_factory(reminder, FROZEN_NOW + timedelta(hours=1))
        await sharing.accept(friend.id, reminder.id)

        await sharing.leave(friend.id, reminder.id)
        await sharing.leave(friend.id, reminder.id)

        assert await deliveries_of(db_session, reminder.id, friend.id) == []
        assert await recipient_of(db_session, reminder.id, friend.id) is None

    async def test_a_stranger_cannot_read_a_reminder_shared_with_somebody_else(
        self, db_session, fake_clock, reminder_factory, user_factory
    ):
        """A crafted `i:<id>:open` from someone who was never invited.

        The recipient row is what grants the screen, so there is nothing to
        show and nothing to leave.
        """
        reminder = await reminder_factory()
        stranger = await user_factory()
        sharing = service(db_session, fake_clock)

        with pytest.raises(NotFoundError):
            await sharing.get_watched(stranger.id, reminder.id)
        with pytest.raises(NotFoundError):
            await sharing.accept(stranger.id, reminder.id)

    async def test_a_watcher_cannot_leave_a_reminder_they_own(
        self, db_session, fake_clock, reminder_factory
    ):
        """`leave` never touches the owner row: the reminder would lose it."""
        reminder = await reminder_factory()
        await service(db_session, fake_clock).leave(reminder.owner_id, reminder.id)

        row = await recipient_of(db_session, reminder.id, reminder.owner_id)
        assert row is not None
        assert row.role is RecipientRole.OWNER


class TestWhatEachSideSees:
    async def test_the_owner_sees_who_is_in_and_who_is_deciding(
        self, db_session, fake_clock, reminder_factory, user_factory
    ):
        reminder = await reminder_factory()
        accepted_friend = await user_factory()
        pending_friend = await user_factory()
        sharing = service(db_session, fake_clock)
        invite = await sharing.issue_invite(reminder.owner_id, reminder.id)
        await sharing.open_invite(invite.token, accepted_friend)
        await sharing.accept(accepted_friend.id, reminder.id)
        await sharing.open_invite(invite.token, pending_friend)

        participants = await sharing.list_participants(reminder.owner_id, reminder.id)

        by_id = {entry.user.id: entry for entry in participants}
        assert by_id[reminder.owner_id].role is RecipientRole.OWNER
        assert by_id[accepted_friend.id].accepted is True
        assert by_id[pending_friend.id].accepted is False
        assert await sharing.count_watchers(reminder.id) == 1

    async def test_a_watcher_lists_what_was_shared_with_them(
        self, db_session, fake_clock, reminder_factory, user_factory
    ):
        reminder = await reminder_factory()
        friend = await user_factory()
        sharing = service(db_session, fake_clock)
        invite = await sharing.issue_invite(reminder.owner_id, reminder.id)
        await sharing.open_invite(invite.token, friend)
        await sharing.accept(friend.id, reminder.id)

        items, total = await sharing.list_shared_with(friend.id, page=0, page_size=8)

        assert total == 1
        assert items[0].reminder.id == reminder.id
        assert items[0].owner is not None and items[0].owner.id == reminder.owner_id
        assert items[0].accepted is True

    async def test_a_watcher_does_not_see_the_reminder_in_their_own_list(
        self, db_session, fake_clock, reminder_factory, user_factory
    ):
        """`/list` is what the user owns (tech.md 21.1, 22.11)."""
        from app.services.reminders import RemindersService

        reminder = await reminder_factory()
        friend = await user_factory()
        sharing = service(db_session, fake_clock)
        invite = await sharing.issue_invite(reminder.owner_id, reminder.id)
        await sharing.open_invite(invite.token, friend)
        await sharing.accept(friend.id, reminder.id)

        _, total = await RemindersService(db_session, fake_clock).list_for_owner(
            friend.id, page=0, page_size=8
        )
        assert total == 0

    async def test_a_watcher_may_not_edit_somebody_elses_reminder(
        self, db_session, fake_clock, reminder_factory, user_factory
    ):
        from app.services.reminders import RemindersService

        reminder = await reminder_factory()
        friend = await user_factory()
        sharing = service(db_session, fake_clock)
        invite = await sharing.issue_invite(reminder.owner_id, reminder.id)
        await sharing.open_invite(invite.token, friend)
        await sharing.accept(friend.id, reminder.id)

        with pytest.raises(PermissionDeniedError):
            await RemindersService(db_session, fake_clock).update(
                friend.id, reminder.id, title="моё теперь"
            )

    async def test_deleting_the_reminder_takes_the_invitation_with_it(
        self, db_session, fake_clock, reminder_factory, user_factory
    ):
        from app.services.reminders import RemindersService

        reminder = await reminder_factory()
        friend = await user_factory()
        sharing = service(db_session, fake_clock)
        invite = await sharing.issue_invite(reminder.owner_id, reminder.id)
        await sharing.open_invite(invite.token, friend)

        await RemindersService(db_session, fake_clock).delete(reminder.owner_id, reminder.id)

        assert await invites_of(db_session, reminder.id) == []
        assert await recipient_of(db_session, reminder.id, friend.id) is None

    async def test_pausing_takes_back_the_watchers_queue_too(
        self,
        db_session,
        fake_clock,
        reminder_factory,
        user_factory,
        occurrence_factory,
    ):
        """A pause that still delivers to the watcher is not a pause either."""
        from app.domain.contracts import ReminderStatus
        from app.services.reminders import RemindersService

        reminder = await reminder_factory()
        friend = await user_factory()
        sharing = service(db_session, fake_clock)
        invite = await sharing.issue_invite(reminder.owner_id, reminder.id)
        await sharing.open_invite(invite.token, friend)
        await occurrence_factory(reminder, FROZEN_NOW + timedelta(hours=1))
        await sharing.accept(friend.id, reminder.id)

        await RemindersService(db_session, fake_clock).set_status(
            reminder.owner_id, reminder.id, ReminderStatus.PAUSED
        )

        assert await deliveries_of(db_session, reminder.id, friend.id) == []


class TestReacting:
    async def test_one_recipient_reacting_does_not_close_the_occurrence(
        self,
        db_session,
        fake_clock,
        reminder_factory,
        user_factory,
        occurrence_factory,
        delivery_factory,
    ):
        """An occurrence closes when every delivery is terminal (tech.md 7.4)."""
        from app.services.reactions import ReactionsService

        reminder = await reminder_factory()
        friend = await user_factory()
        occurrence = await occurrence_factory(reminder, FROZEN_NOW, status=OccurrenceStatus.SENT)
        owner_delivery = await delivery_factory(
            occurrence, reminder.owner_id, status=DeliveryStatus.SENT
        )
        friend_delivery = await delivery_factory(occurrence, friend.id, status=DeliveryStatus.SENT)
        await db_session.commit()

        reactions = ReactionsService(db_session, fake_clock)
        await reactions.react(friend_delivery.id, friend.id, "done")
        await db_session.refresh(occurrence)
        assert occurrence.status is OccurrenceStatus.SENT

        await reactions.react(owner_delivery.id, reminder.owner_id, "done")
        await db_session.refresh(occurrence)
        assert occurrence.status is OccurrenceStatus.DONE
