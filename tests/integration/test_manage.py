"""Acceptance criteria of S9 against a real database (tech.md 15, 21.3, 21.4).

What a user is promised: a paused reminder stops arriving, an edited schedule
replaces the old one instead of joining it, a deleted reminder takes its history
with it, and `/today` shows the day the user is actually living in.
"""

from datetime import UTC, datetime, time, timedelta

import pytest
import sqlalchemy as sa

from app.db.models import Delivery, Occurrence
from app.domain.contracts import DeliveryStatus, OccurrenceStatus, ReminderStatus
from app.domain.errors import NotFoundError, PermissionDeniedError, ScheduleExhaustedError
from app.domain.reminders import build_daily_schedule, build_once_schedule
from app.services.reminders import RemindersService
from app.services.today import TodayService
from tests.conftest import FROZEN_NOW


def service(session, clock) -> RemindersService:
    return RemindersService(session, clock)


async def queued(session, reminder_id: int) -> int:
    stmt = sa.select(sa.func.count()).where(Occurrence.reminder_id == reminder_id)
    return int((await session.execute(stmt)).scalar_one())


class TestPause:
    """A pause that still delivers is not a pause (tech.md 21.3)."""

    async def test_pausing_takes_back_what_was_queued(
        self, db_session, fake_clock, reminder_factory, occurrence_factory
    ):
        reminder = await reminder_factory(planned_until=FROZEN_NOW + timedelta(days=2))
        reminder.fired_count = 2
        await occurrence_factory(reminder, FROZEN_NOW + timedelta(hours=1))
        await occurrence_factory(reminder, FROZEN_NOW + timedelta(hours=3))
        await db_session.commit()

        await service(db_session, fake_clock).set_status(
            reminder.owner_id, reminder.id, ReminderStatus.PAUSED
        )

        assert await queued(db_session, reminder.id) == 0
        assert reminder.status is ReminderStatus.PAUSED
        assert reminder.planned_until is None
        assert reminder.fired_count == 0

    async def test_pausing_twice_takes_back_the_same_rows_once(
        self, db_session, fake_clock, reminder_factory, occurrence_factory
    ):
        """Idempotency (tech.md 10): the second press changes nothing."""
        reminder = await reminder_factory()
        reminder.fired_count = 1
        await occurrence_factory(reminder, FROZEN_NOW + timedelta(hours=1))
        await db_session.commit()

        pause = service(db_session, fake_clock)
        await pause.set_status(reminder.owner_id, reminder.id, ReminderStatus.PAUSED)
        after_first = (reminder.fired_count, await queued(db_session, reminder.id))
        await pause.set_status(reminder.owner_id, reminder.id, ReminderStatus.PAUSED)

        assert (reminder.fired_count, await queued(db_session, reminder.id)) == after_first
        assert reminder.fired_count == 0

    async def test_a_message_already_on_screen_keeps_its_buttons(
        self, db_session, fake_clock, reminder_factory, occurrence_factory, delivery_factory
    ):
        """A sent occurrence survives the pause: somebody is looking at it."""
        reminder = await reminder_factory()
        sent = await occurrence_factory(
            reminder, FROZEN_NOW - timedelta(minutes=5), status=OccurrenceStatus.SENT
        )
        await delivery_factory(sent, reminder.owner_id, status=DeliveryStatus.SENT)
        pending = await occurrence_factory(reminder, FROZEN_NOW + timedelta(hours=1))
        await delivery_factory(pending, reminder.owner_id)
        await db_session.commit()

        await service(db_session, fake_clock).set_status(
            reminder.owner_id, reminder.id, ReminderStatus.PAUSED
        )

        left = (await db_session.execute(sa.select(Occurrence.id))).scalars().all()
        assert left == [sent.id]

    async def test_a_snoozed_delivery_is_not_taken_back_either(
        self, db_session, fake_clock, reminder_factory, occurrence_factory, delivery_factory
    ):
        """The user asked for it later; a pause must not swallow that request."""
        reminder = await reminder_factory()
        occurrence = await occurrence_factory(reminder, FROZEN_NOW + timedelta(hours=1))
        await delivery_factory(occurrence, reminder.owner_id, status=DeliveryStatus.SNOOZED)
        await db_session.commit()

        await service(db_session, fake_clock).set_status(
            reminder.owner_id, reminder.id, ReminderStatus.PAUSED
        )

        assert await queued(db_session, reminder.id) == 1

    async def test_resuming_lets_the_planner_start_over(
        self, db_session, fake_clock, reminder_factory
    ):
        reminder = await reminder_factory(
            status=ReminderStatus.PAUSED, planned_until=FROZEN_NOW + timedelta(days=2)
        )
        await db_session.commit()

        resumed = await service(db_session, fake_clock).set_status(
            reminder.owner_id, reminder.id, ReminderStatus.ACTIVE
        )

        assert resumed.status is ReminderStatus.ACTIVE
        # Resuming leaves the horizon alone: nothing was taken back, so nothing
        # has to be replanned before the planner reaches its own boundary.
        assert resumed.planned_until == FROZEN_NOW + timedelta(days=2)

    async def test_an_archived_reminder_cannot_be_revived(
        self, db_session, fake_clock, reminder_factory
    ):
        reminder = await reminder_factory(status=ReminderStatus.ARCHIVED)
        await db_session.commit()

        with pytest.raises(PermissionDeniedError):
            await service(db_session, fake_clock).set_status(
                reminder.owner_id, reminder.id, ReminderStatus.ACTIVE
            )


class TestEdit:
    async def test_a_new_title_is_normalized_the_way_creation_normalizes_it(
        self, db_session, fake_clock, reminder_factory
    ):
        reminder = await reminder_factory()
        await db_session.commit()

        edited = await service(db_session, fake_clock).update(
            reminder.owner_id, reminder.id, title="  Пить   воду  "
        )

        assert edited.title == "Пить воду"

    async def test_a_new_schedule_replaces_what_the_old_one_had_queued(
        self, db_session, fake_clock, reminder_factory, occurrence_factory
    ):
        """Queued moments belong to the schedule that just went away."""
        reminder = await reminder_factory(planned_until=FROZEN_NOW + timedelta(days=2))
        await occurrence_factory(reminder, FROZEN_NOW + timedelta(hours=1))
        await db_session.commit()

        edited = await service(db_session, fake_clock).update(
            reminder.owner_id, reminder.id, schedule=build_daily_schedule([time(8, 0)])
        )

        assert isinstance(edited.schedule, dict) and edited.schedule["kind"] == "daily"
        assert edited.schedule_kind.value == "daily"
        assert await queued(db_session, reminder.id) == 0
        assert edited.planned_until is None

    async def test_a_schedule_with_nothing_ahead_leaves_the_row_alone(
        self, db_session, fake_clock, reminder_factory
    ):
        reminder = await reminder_factory()
        await db_session.commit()
        before = dict(reminder.schedule)

        with pytest.raises(ScheduleExhaustedError):
            await service(db_session, fake_clock).update(
                reminder.owner_id,
                reminder.id,
                schedule=build_once_schedule((FROZEN_NOW - timedelta(days=1)).date(), time(7, 0)),
            )

        assert reminder.schedule == before

    async def test_the_timezone_snapshot_is_never_touched(
        self, db_session, fake_clock, reminder_factory, user_factory
    ):
        """The schedule was expanded in it, so swapping it moves every moment."""
        owner = await user_factory(timezone="Europe/Berlin")
        reminder = await reminder_factory(owner=owner)
        await db_session.commit()

        edited = await service(db_session, fake_clock).update(owner.id, reminder.id, title="Другое")

        assert edited.timezone == "Europe/Berlin"

    async def test_a_note_can_be_written_and_taken_away(
        self, db_session, fake_clock, reminder_factory
    ):
        reminder = await reminder_factory()
        await db_session.commit()
        editor = service(db_session, fake_clock)

        await editor.update(reminder.owner_id, reminder.id, note="после еды")
        assert reminder.note == "после еды"

        await editor.update(reminder.owner_id, reminder.id, clear_note=True)
        assert reminder.note is None

    async def test_the_repeat_can_be_set_and_switched_off(
        self, db_session, fake_clock, reminder_factory
    ):
        reminder = await reminder_factory()
        await db_session.commit()
        editor = service(db_session, fake_clock)

        await editor.update(reminder.owner_id, reminder.id, repeat_after_minutes=30)
        assert reminder.repeat_after_minutes == 30

        await editor.update(reminder.owner_id, reminder.id, clear_repeat=True)
        assert reminder.repeat_after_minutes is None

    async def test_the_snooze_step_is_stored_as_given(
        self, db_session, fake_clock, reminder_factory
    ):
        reminder = await reminder_factory()
        await db_session.commit()

        edited = await service(db_session, fake_clock).update(
            reminder.owner_id, reminder.id, snooze_minutes=25
        )

        assert edited.snooze_minutes == 25

    async def test_a_reminder_moves_to_another_category_of_its_own(
        self, db_session, fake_clock, reminder_factory, category_factory
    ):
        target = await category_factory()
        reminder = await reminder_factory()
        await db_session.commit()

        edited = await service(db_session, fake_clock).update(
            reminder.owner_id, reminder.id, category_id=target.id
        )

        assert edited.category_id == target.id

    async def test_editing_nothing_changes_nothing(self, db_session, fake_clock, reminder_factory):
        """Every field defaults to "leave it alone", so an empty call is a no-op."""
        reminder = await reminder_factory(note="было", repeat_after_minutes=15)
        await db_session.commit()

        edited = await service(db_session, fake_clock).update(reminder.owner_id, reminder.id)

        assert (edited.note, edited.repeat_after_minutes) == ("было", 15)

    async def test_an_archived_category_is_refused(
        self, db_session, fake_clock, reminder_factory, category_factory
    ):
        archived = await category_factory(archived_at=FROZEN_NOW)
        reminder = await reminder_factory()
        await db_session.commit()

        with pytest.raises(NotFoundError):
            await service(db_session, fake_clock).update(
                reminder.owner_id, reminder.id, category_id=archived.id
            )

    async def test_someone_elses_category_is_refused(
        self, db_session, fake_clock, reminder_factory, category_factory, user_factory
    ):
        stranger = await user_factory()
        theirs = await category_factory(owner_id=stranger.id, is_system=False)
        reminder = await reminder_factory()
        await db_session.commit()

        with pytest.raises(PermissionDeniedError):
            await service(db_session, fake_clock).update(
                reminder.owner_id, reminder.id, category_id=theirs.id
            )

    async def test_someone_elses_reminder_is_refused(
        self, db_session, fake_clock, reminder_factory, user_factory
    ):
        stranger = await user_factory()
        reminder = await reminder_factory()
        await db_session.commit()

        with pytest.raises(PermissionDeniedError):
            await service(db_session, fake_clock).update(stranger.id, reminder.id, title="Чужое")


class TestDelete:
    async def test_deleting_takes_the_whole_history_with_it(
        self, db_session, fake_clock, reminder_factory, occurrence_factory, delivery_factory
    ):
        reminder = await reminder_factory()
        occurrence = await occurrence_factory(reminder)
        await delivery_factory(occurrence, reminder.owner_id, status=DeliveryStatus.DONE)
        await db_session.commit()

        await service(db_session, fake_clock).delete(reminder.owner_id, reminder.id)

        assert await queued(db_session, reminder.id) == 0
        left = (
            await db_session.execute(sa.select(sa.func.count()).select_from(Delivery))
        ).scalar_one()
        assert left == 0

    async def test_deleting_a_reminder_that_is_gone_is_not_found(
        self, db_session, fake_clock, user_factory
    ):
        user = await user_factory()
        await db_session.commit()

        with pytest.raises(NotFoundError):
            await service(db_session, fake_clock).delete(user.id, 999_999)


class TestList:
    async def test_the_filter_narrows_the_page_and_the_total(
        self, db_session, fake_clock, user_factory, category_factory, reminder_factory
    ):
        owner = await user_factory()
        water = await category_factory()
        pills = await category_factory()
        await reminder_factory(owner=owner, category=water)
        await reminder_factory(owner=owner, category=pills)
        await reminder_factory(owner=owner, category=pills)
        await db_session.commit()

        items, total = await service(db_session, fake_clock).list_for_owner(
            owner.id, page=0, page_size=8, category_id=pills.id
        )

        assert total == 2
        assert {item.category_id for item in items} == {pills.id}

    async def test_an_archived_reminder_never_shows_up(
        self, db_session, fake_clock, user_factory, reminder_factory
    ):
        owner = await user_factory()
        await reminder_factory(owner=owner, status=ReminderStatus.ARCHIVED)
        await db_session.commit()

        items, total = await service(db_session, fake_clock).list_for_owner(
            owner.id, page=0, page_size=8
        )

        assert (list(items), total) == ([], 0)


class TestToday:
    async def test_the_day_is_the_users_own_day(
        self,
        db_session,
        fake_clock,
        user_factory,
        reminder_factory,
        occurrence_factory,
        delivery_factory,
    ):
        """Moscow noon and Berlin noon are different instants, and `/today`
        answers in the timezone of whoever asked."""
        owner = await user_factory(timezone="Europe/Moscow")
        reminder = await reminder_factory(owner=owner)
        # 22:30 UTC is already tomorrow in Moscow and still today in Berlin.
        tomorrow_in_moscow = datetime(2026, 6, 1, 22, 30, tzinfo=UTC)
        inside = await occurrence_factory(reminder, datetime(2026, 6, 1, 9, 0, tzinfo=UTC))
        await delivery_factory(inside, owner.id, status=DeliveryStatus.DONE)
        outside = await occurrence_factory(reminder, tomorrow_in_moscow)
        await delivery_factory(outside, owner.id)
        await db_session.commit()

        entries, total = await TodayService(db_session, fake_clock).list_for_user(
            owner, page=0, page_size=8
        )

        assert total == 1
        assert entries[0].status is DeliveryStatus.DONE
        assert entries[0].title == reminder.title

    async def test_a_delivery_addressed_to_somebody_else_is_not_my_day(
        self,
        db_session,
        fake_clock,
        user_factory,
        reminder_factory,
        occurrence_factory,
        delivery_factory,
    ):
        """The day is built from deliveries, so it is per recipient (tech.md 21.9)."""
        owner = await user_factory()
        watcher = await user_factory()
        reminder = await reminder_factory(owner=owner)
        occurrence = await occurrence_factory(reminder, FROZEN_NOW)
        await delivery_factory(occurrence, owner.id)
        await db_session.commit()

        entries, total = await TodayService(db_session, fake_clock).list_for_user(
            watcher, page=0, page_size=8
        )

        assert (list(entries), total) == ([], 0)

    async def test_the_day_is_ordered_by_the_moment_it_fires(
        self,
        db_session,
        fake_clock,
        user_factory,
        reminder_factory,
        occurrence_factory,
        delivery_factory,
    ):
        owner = await user_factory(timezone="Europe/Moscow")
        reminder = await reminder_factory(owner=owner)
        late = await occurrence_factory(reminder, datetime(2026, 6, 1, 17, 0, tzinfo=UTC))
        early = await occurrence_factory(reminder, datetime(2026, 6, 1, 5, 0, tzinfo=UTC))
        await delivery_factory(late, owner.id)
        await delivery_factory(early, owner.id)
        await db_session.commit()

        entries, _ = await TodayService(db_session, fake_clock).list_for_user(
            owner, page=0, page_size=8
        )

        assert [entry.fire_at for entry in entries] == sorted(entry.fire_at for entry in entries)
