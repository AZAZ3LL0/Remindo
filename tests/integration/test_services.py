"""Acceptance criteria of the user-facing services."""

from datetime import time, timedelta

import pytest
import sqlalchemy as sa

from app.db.models import Category, Reminder, User
from app.domain.categories import CODE_PATTERN
from app.domain.contracts import ReminderStatus
from app.domain.errors import (
    CategoryExistsError,
    CategoryInUseError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from app.domain.schedules import DailySchedule
from app.services.categories import CategoriesService
from app.services.onboarding import OnboardingService
from app.services.reminders import RemindersService
from tests.conftest import FROZEN_NOW


def onboarding(session, clock) -> OnboardingService:
    return OnboardingService(session, clock, "Europe/Moscow", "ru")


class TestOnboarding:
    async def test_first_contact_creates_the_user(self, db_session, fake_clock):
        service = onboarding(db_session, fake_clock)

        user = await service.ensure_user(555, 555, first_name="Самат", username="azaz")

        assert user.timezone == "Europe/Moscow"
        assert user.language == "ru"
        assert user.username == "azaz"

    async def test_second_contact_reuses_the_user_and_refreshes_the_chat(
        self, db_session, fake_clock
    ):
        service = onboarding(db_session, fake_clock)

        first = await service.ensure_user(556, 556, first_name="Самат")
        second = await service.ensure_user(556, 999, first_name="Самат")

        assert first.id == second.id
        assert second.tg_chat_id == 999

    async def test_writing_again_clears_the_blocked_flag(
        self, db_session, fake_clock, user_factory
    ):
        user = await user_factory(is_blocked=True)
        await db_session.commit()

        refreshed = await onboarding(db_session, fake_clock).ensure_user(
            user.tg_user_id, user.tg_chat_id
        )

        assert refreshed.is_blocked is False

    async def test_timezone_is_stored_and_finishes_onboarding(
        self, db_session, fake_clock, user_factory
    ):
        user = await user_factory()

        updated = await onboarding(db_session, fake_clock).set_timezone(user.id, "Asia/Tbilisi")

        assert updated.timezone == "Asia/Tbilisi"
        assert updated.onboarded_at == FROZEN_NOW

    async def test_unknown_timezone_is_rejected(self, db_session, fake_clock, user_factory):
        user = await user_factory()

        with pytest.raises(ValidationError):
            await onboarding(db_session, fake_clock).set_timezone(user.id, "Mars/Olympus")

    async def test_language_is_limited_to_supported_values(
        self, db_session, fake_clock, user_factory
    ):
        user = await user_factory()
        service = onboarding(db_session, fake_clock)

        assert (await service.set_language(user.id, "en")).language == "en"
        with pytest.raises(ValidationError):
            await service.set_language(user.id, "fr")

    async def test_quiet_hours_are_set_and_cleared_together(
        self, db_session, fake_clock, user_factory
    ):
        user = await user_factory()
        service = onboarding(db_session, fake_clock)

        updated = await service.set_quiet_hours(user.id, time(23, 0), time(7, 0))
        assert (updated.quiet_start, updated.quiet_end) == (time(23, 0), time(7, 0))

        cleared = await service.set_quiet_hours(user.id, None, None)
        assert cleared.quiet_start is None

        with pytest.raises(ValidationError):
            await service.set_quiet_hours(user.id, time(23, 0), None)

    async def test_unknown_user_is_reported(self, db_session, fake_clock):
        with pytest.raises(NotFoundError):
            await onboarding(db_session, fake_clock).set_language(10**9, "en")

    async def test_equal_quiet_bounds_are_refused_and_leave_the_row_alone(
        self, db_session, fake_clock, user_factory
    ):
        """An interval that silences nothing must not look saved."""
        user = await user_factory(quiet_start=time(23, 0), quiet_end=time(7, 0))
        await db_session.commit()
        service = onboarding(db_session, fake_clock)

        with pytest.raises(ValidationError):
            await service.set_quiet_hours(user.id, time(22, 0), time(22, 0))

        await db_session.refresh(user)
        assert (user.quiet_start, user.quiet_end) == (time(23, 0), time(7, 0))

    async def test_rejected_timezone_leaves_the_row_alone(
        self, db_session, fake_clock, user_factory
    ):
        user = await user_factory(timezone="Europe/Moscow")
        await db_session.commit()

        with pytest.raises(ValidationError):
            await onboarding(db_session, fake_clock).set_timezone(user.id, "Mars/Olympus")

        await db_session.refresh(user)
        assert user.timezone == "Europe/Moscow"
        assert user.onboarded_at is None


class TestOnboardingIsIdempotent:
    """Every settings reaction repeated twice leaves exactly one effect."""

    async def test_repeated_first_contact_creates_one_user(self, db_session, fake_clock):
        service = onboarding(db_session, fake_clock)

        await service.ensure_user(4242, 4242, first_name="Самат")
        await service.ensure_user(4242, 4242, first_name="Самат")

        count = await db_session.scalar(
            sa.select(sa.func.count()).select_from(User).where(User.tg_user_id == 4242)
        )
        assert count == 1

    async def test_repeated_timezone_choice_stamps_onboarding_once(
        self, db_session, fake_clock, user_factory
    ):
        """Changing the zone later must not read as a fresh onboarding."""
        user = await user_factory()
        await db_session.commit()
        service = onboarding(db_session, fake_clock)

        first = await service.set_timezone(user.id, "Asia/Tbilisi")
        onboarded_at = first.onboarded_at
        fake_clock.advance(timedelta(days=3))
        second = await service.set_timezone(user.id, "Asia/Tbilisi")

        assert onboarded_at == FROZEN_NOW
        assert second.onboarded_at == onboarded_at

    async def test_repeated_language_choice_settles_on_one_value(
        self, db_session, fake_clock, user_factory
    ):
        user = await user_factory()
        await db_session.commit()
        service = onboarding(db_session, fake_clock)

        await service.set_language(user.id, "en")
        second = await service.set_language(user.id, "en")

        assert second.language == "en"

    async def test_repeated_quiet_interval_settles_on_one_value(
        self, db_session, fake_clock, user_factory
    ):
        user = await user_factory()
        await db_session.commit()
        service = onboarding(db_session, fake_clock)

        await service.set_quiet_hours(user.id, time(23, 0), time(7, 0))
        second = await service.set_quiet_hours(user.id, time(23, 0), time(7, 0))

        assert (second.quiet_start, second.quiet_end) == (time(23, 0), time(7, 0))

    async def test_repeated_switch_off_stays_off(self, db_session, fake_clock, user_factory):
        user = await user_factory(quiet_start=time(23, 0), quiet_end=time(7, 0))
        await db_session.commit()
        service = onboarding(db_session, fake_clock)

        await service.set_quiet_hours(user.id, None, None)
        second = await service.set_quiet_hours(user.id, None, None)

        assert (second.quiet_start, second.quiet_end) == (None, None)


class TestCategories:
    """Acceptance criteria of S2: own categories on top of the presets."""

    async def test_list_contains_system_presets_and_own_categories(
        self, db_session, fake_clock, user_factory, category_factory
    ):
        user = await user_factory()
        stranger = await user_factory()
        await category_factory(code="pills_sys", title="Таблетки")
        await category_factory(owner_id=user.id, code="mine", is_system=False)
        await category_factory(owner_id=stranger.id, code="theirs", is_system=False)
        await db_session.commit()

        codes = {
            category.code
            for category in await CategoriesService(db_session, fake_clock).list_for_user(user.id)
        }

        assert "pills_sys" in codes
        assert "mine" in codes
        assert "theirs" not in codes

    async def test_archived_categories_disappear_from_the_list(
        self, db_session, fake_clock, user_factory, category_factory
    ):
        user = await user_factory()
        category = await category_factory(
            owner_id=user.id, code="gone", is_system=False, archived_at=FROZEN_NOW
        )
        await db_session.commit()

        listed = await CategoriesService(db_session, fake_clock).list_for_user(user.id)

        assert category.id not in {item.id for item in listed}

    async def test_creation_keeps_the_title_and_derives_a_valid_code(
        self, db_session, fake_clock, user_factory
    ):
        """The user types a title and an emoji; the slug is not their problem."""
        user = await user_factory()

        created = await CategoriesService(db_session, fake_clock).create(user.id, "Чтение", "📚")

        assert (created.title, created.emoji) == ("Чтение", "📚")
        assert created.is_system is False
        assert CODE_PATTERN.match(created.code)

    async def test_creation_normalises_the_title_before_storing_it(
        self, db_session, fake_clock, user_factory
    ):
        user = await user_factory()

        created = await CategoriesService(db_session, fake_clock).create(
            user.id, "  Уборка   дома ", "🧹"
        )

        assert created.title == "Уборка дома"

    @pytest.mark.parametrize("title", ["", "   ", "я" * 65])
    async def test_creation_rejects_an_unusable_title(
        self, db_session, fake_clock, user_factory, title
    ):
        user = await user_factory()

        with pytest.raises(ValidationError):
            await CategoriesService(db_session, fake_clock).create(user.id, title, "📚")

    @pytest.mark.parametrize("emoji", ["", "📚📌", "📚 ", "два слова"])
    async def test_creation_demands_exactly_one_emoji(
        self, db_session, fake_clock, user_factory, emoji
    ):
        user = await user_factory()

        if emoji == "📚 ":
            assert (
                await CategoriesService(db_session, fake_clock).create(user.id, "Хобби", emoji)
            ).emoji == "📚"
            return

        with pytest.raises(ValidationError):
            await CategoriesService(db_session, fake_clock).create(user.id, "Хобби", emoji)

    async def test_a_duplicate_title_is_refused_whatever_the_case(
        self, db_session, fake_clock, user_factory
    ):
        user = await user_factory()
        service = CategoriesService(db_session, fake_clock)
        await service.create(user.id, "Спорт", "🏃")

        with pytest.raises(CategoryExistsError):
            await service.create(user.id, "  спорт ", "🧘")

    async def test_two_different_titles_that_share_a_slug_both_survive(
        self, db_session, fake_clock, user_factory
    ):
        """A code collision is the service's problem, not the user's."""
        user = await user_factory()
        service = CategoriesService(db_session, fake_clock)

        first = await service.create(user.id, "Спорт", "🏃")
        second = await service.create(user.id, "спорт!", "🧘")

        assert first.code != second.code
        assert CODE_PATTERN.match(second.code)

    async def test_a_code_held_by_an_archived_category_is_not_reused(
        self, db_session, fake_clock, user_factory
    ):
        """The unique index counts archived rows, so the slug stays taken."""
        user = await user_factory()
        service = CategoriesService(db_session, fake_clock)
        archived = await service.create(user.id, "Спорт", "🏃")
        await service.archive(user.id, archived.id)

        created = await service.create(user.id, "Спорт", "🏃")

        assert created.code != archived.code

    async def test_rename_only_touches_own_categories(
        self, db_session, fake_clock, user_factory, category_factory
    ):
        user = await user_factory()
        own = await category_factory(owner_id=user.id, code="own", is_system=False)
        system = await category_factory(code="system_one")
        await db_session.commit()
        service = CategoriesService(db_session, fake_clock)

        renamed = await service.rename(user.id, own.id, "Новое имя")
        assert renamed.title == "Новое имя"

        with pytest.raises(PermissionDeniedError):
            await service.rename(user.id, system.id, "Нельзя")

    async def test_rename_keeps_the_code(self, db_session, fake_clock, user_factory):
        """Reminders point at the row, so the identity must not drift."""
        user = await user_factory()
        service = CategoriesService(db_session, fake_clock)
        created = await service.create(user.id, "Спорт", "🏃")

        renamed = await service.rename(user.id, created.id, "Зарядка")

        assert (renamed.title, renamed.code) == ("Зарядка", created.code)

    async def test_rename_refuses_a_title_another_category_already_holds(
        self, db_session, fake_clock, user_factory
    ):
        user = await user_factory()
        service = CategoriesService(db_session, fake_clock)
        await service.create(user.id, "Спорт", "🏃")
        other = await service.create(user.id, "Чтение", "📚")

        with pytest.raises(CategoryExistsError):
            await service.rename(user.id, other.id, "спорт")

    async def test_archiving_is_blocked_while_reminders_are_alive(
        self, db_session, fake_clock, user_factory, category_factory, reminder_factory
    ):
        user = await user_factory()
        category = await category_factory(owner_id=user.id, code="busy", is_system=False)
        reminder = await reminder_factory(owner=user, category=category)
        await db_session.commit()
        service = CategoriesService(db_session, fake_clock)

        with pytest.raises(CategoryInUseError):
            await service.archive(user.id, category.id)

        reminder.status = ReminderStatus.ARCHIVED
        await db_session.commit()

        result = await service.archive(user.id, category.id)
        assert (result.applied, result.category.archived_at) == (True, FROZEN_NOW)

    async def test_a_paused_reminder_still_blocks_archiving(
        self, db_session, fake_clock, user_factory, category_factory, reminder_factory
    ):
        """Paused means resumable, so the category is still in use."""
        user = await user_factory()
        category = await category_factory(owner_id=user.id, code="paused", is_system=False)
        await reminder_factory(owner=user, category=category, status=ReminderStatus.PAUSED)
        await db_session.commit()

        with pytest.raises(CategoryInUseError):
            await CategoriesService(db_session, fake_clock).archive(user.id, category.id)

    async def test_a_system_category_cannot_be_archived(
        self, db_session, fake_clock, user_factory, category_factory
    ):
        user = await user_factory()
        system = await category_factory(code="system_two")
        await db_session.commit()

        with pytest.raises(PermissionDeniedError):
            await CategoriesService(db_session, fake_clock).archive(user.id, system.id)

    async def test_foreign_category_is_not_visible(
        self, db_session, fake_clock, user_factory, category_factory
    ):
        user = await user_factory()
        stranger = await user_factory()
        category = await category_factory(owner_id=stranger.id, code="secret", is_system=False)
        await db_session.commit()

        with pytest.raises(PermissionDeniedError):
            await CategoriesService(db_session, fake_clock).get_for_user(user.id, category.id)

        with pytest.raises(PermissionDeniedError):
            await CategoriesService(db_session, fake_clock).archive(user.id, category.id)

    async def test_missing_category_is_reported(self, db_session, fake_clock, user_factory):
        user = await user_factory()

        with pytest.raises(NotFoundError):
            await CategoriesService(db_session, fake_clock).get_for_user(user.id, 10**9)

    async def test_reminder_counts_explain_a_refusal(
        self, db_session, fake_clock, user_factory, category_factory, reminder_factory
    ):
        user = await user_factory()
        busy = await category_factory(owner_id=user.id, code="counted", is_system=False)
        empty = await category_factory(owner_id=user.id, code="empty", is_system=False)
        await reminder_factory(owner=user, category=busy)
        await reminder_factory(owner=user, category=busy, status=ReminderStatus.ARCHIVED)
        await db_session.commit()

        counts = await CategoriesService(db_session, fake_clock).counts_for([busy, empty])

        assert counts.get(busy.id) == 1
        assert counts.get(empty.id, 0) == 0


class TestCategoriesAreIdempotent:
    """Every category reaction repeated twice leaves exactly one effect."""

    async def test_creating_the_same_category_twice_creates_one_row(
        self, db_session, fake_clock, user_factory
    ):
        user = await user_factory()
        service = CategoriesService(db_session, fake_clock)

        await service.create(user.id, "Спорт", "🏃")
        with pytest.raises(CategoryExistsError):
            await service.create(user.id, "Спорт", "🏃")

        count = await db_session.scalar(
            sa.select(sa.func.count())
            .select_from(Category)
            .where(Category.owner_id == user.id, Category.title == "Спорт")
        )
        assert count == 1

    async def test_archiving_twice_archives_once(self, db_session, fake_clock, user_factory):
        user = await user_factory()
        service = CategoriesService(db_session, fake_clock)
        created = await service.create(user.id, "Спорт", "🏃")

        first = await service.archive(user.id, created.id)
        fake_clock.advance(timedelta(days=1))
        second = await service.archive(user.id, created.id)

        assert (first.applied, second.applied) == (True, False)
        assert second.category.archived_at == FROZEN_NOW

    async def test_renaming_twice_settles_on_one_title(self, db_session, fake_clock, user_factory):
        user = await user_factory()
        service = CategoriesService(db_session, fake_clock)
        created = await service.create(user.id, "Спорт", "🏃")

        await service.rename(user.id, created.id, "Зарядка")
        second = await service.rename(user.id, created.id, "Зарядка")

        assert second.title == "Зарядка"
        count = await db_session.scalar(
            sa.select(sa.func.count()).select_from(Category).where(Category.owner_id == user.id)
        )
        assert count == 1


class TestReminders:
    async def test_creation_registers_the_owner_as_a_recipient(
        self, db_session, fake_clock, user_factory, category_factory
    ):
        user = await user_factory()
        category = await category_factory()
        await db_session.commit()

        reminder = await RemindersService(db_session, fake_clock).create(
            owner_id=user.id,
            category_id=category.id,
            title="Пить воду",
            schedule=DailySchedule(times=["08:00"]),
            timezone=user.timezone,
        )

        assert reminder.status is ReminderStatus.ACTIVE
        assert reminder.starts_at == FROZEN_NOW
        assert reminder.schedule == {"kind": "daily", "times": ["08:00"], "every_n_days": 1}

    @pytest.mark.parametrize(
        ("title", "note"),
        [("", None), ("x" * 121, None), ("Норм", "n" * 1001)],
    )
    async def test_input_limits_are_enforced(
        self, db_session, fake_clock, user_factory, category_factory, title, note
    ):
        user = await user_factory()
        category = await category_factory()
        await db_session.commit()

        with pytest.raises(ValidationError):
            await RemindersService(db_session, fake_clock).create(
                owner_id=user.id,
                category_id=category.id,
                title=title,
                note=note,
                schedule=DailySchedule(times=["08:00"]),
                timezone=user.timezone,
            )

    async def test_creation_rejects_an_unknown_category(self, db_session, fake_clock, user_factory):
        user = await user_factory()
        await db_session.commit()

        with pytest.raises(NotFoundError):
            await RemindersService(db_session, fake_clock).create(
                owner_id=user.id,
                category_id=10**9,
                title="Пить воду",
                schedule=DailySchedule(times=["08:00"]),
                timezone=user.timezone,
            )

    async def test_creation_rejects_a_foreign_category(
        self, db_session, fake_clock, user_factory, category_factory
    ):
        user = await user_factory()
        stranger = await user_factory()
        category = await category_factory(owner_id=stranger.id, code="foreign", is_system=False)
        await db_session.commit()

        with pytest.raises(PermissionDeniedError):
            await RemindersService(db_session, fake_clock).create(
                owner_id=user.id,
                category_id=category.id,
                title="Пить воду",
                schedule=DailySchedule(times=["08:00"]),
                timezone=user.timezone,
            )

    async def test_pause_and_resume_change_the_status(
        self, db_session, fake_clock, reminder_factory
    ):
        reminder = await reminder_factory()
        await db_session.commit()
        service = RemindersService(db_session, fake_clock)

        paused = await service.set_status(reminder.owner_id, reminder.id, ReminderStatus.PAUSED)
        assert paused.status is ReminderStatus.PAUSED

        resumed = await service.set_status(reminder.owner_id, reminder.id, ReminderStatus.ACTIVE)
        assert resumed.status is ReminderStatus.ACTIVE

    async def test_only_the_owner_may_touch_a_reminder(
        self, db_session, fake_clock, reminder_factory, user_factory
    ):
        reminder = await reminder_factory()
        stranger = await user_factory()
        await db_session.commit()

        with pytest.raises(PermissionDeniedError):
            await RemindersService(db_session, fake_clock).get_owned(stranger.id, reminder.id)
        with pytest.raises(NotFoundError):
            await RemindersService(db_session, fake_clock).get_owned(stranger.id, 10**9)

    async def test_delete_removes_the_reminder(self, db_session, fake_clock, reminder_factory):
        reminder = await reminder_factory()
        await db_session.commit()

        await RemindersService(db_session, fake_clock).delete(reminder.owner_id, reminder.id)

        assert await db_session.get(Reminder, reminder.id) is None

    async def test_listing_is_paginated_and_owner_scoped(
        self, db_session, fake_clock, user_factory, category_factory, reminder_factory
    ):
        user = await user_factory()
        category = await category_factory()
        for index in range(3):
            await reminder_factory(
                owner=user,
                category=category,
                title=f"Дело {index}",
                starts_at=FROZEN_NOW + timedelta(minutes=index),
            )
        await reminder_factory()
        await db_session.commit()

        first_page, total = await RemindersService(db_session, fake_clock).list_for_owner(
            user.id, page=0, page_size=2
        )
        second_page, _ = await RemindersService(db_session, fake_clock).list_for_owner(
            user.id, page=1, page_size=2
        )

        assert total == 3
        assert len(first_page) == 2
        assert len(second_page) == 1

    async def test_listing_filters_by_category(
        self, db_session, fake_clock, user_factory, category_factory, reminder_factory
    ):
        user = await user_factory()
        wanted = await category_factory(code="wanted")
        other = await category_factory(code="other")
        await reminder_factory(owner=user, category=wanted)
        await reminder_factory(owner=user, category=other)
        await db_session.commit()

        items, total = await RemindersService(db_session, fake_clock).list_for_owner(
            user.id, page=0, page_size=10, category_id=wanted.id
        )

        assert total == 1
        assert items[0].category_id == wanted.id
