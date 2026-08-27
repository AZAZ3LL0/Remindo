"""Acceptance criteria of the user-facing services."""

from datetime import time, timedelta

import pytest

from app.db.models import Reminder
from app.domain.contracts import ReminderStatus
from app.domain.errors import (
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


class TestCategories:
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

    async def test_creation_validates_the_slug_and_the_title(
        self, db_session, fake_clock, user_factory
    ):
        user = await user_factory()
        service = CategoriesService(db_session, fake_clock)

        created = await service.create(user.id, "reading", "Чтение", "📚")
        assert created.is_system is False

        with pytest.raises(ValidationError):
            await service.create(user.id, "Reading!", "Чтение", "📚")
        with pytest.raises(ValidationError):
            await service.create(user.id, "reading2", "", "📚")
        with pytest.raises(ValidationError):
            await service.create(user.id, "reading", "Дубль", "📚")

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

    async def test_archiving_is_blocked_while_reminders_are_active(
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

        assert (await service.archive(user.id, category.id)).archived_at == FROZEN_NOW

    async def test_foreign_category_is_not_visible(
        self, db_session, fake_clock, user_factory, category_factory
    ):
        user = await user_factory()
        stranger = await user_factory()
        category = await category_factory(owner_id=stranger.id, code="secret", is_system=False)
        await db_session.commit()

        with pytest.raises(PermissionDeniedError):
            await CategoriesService(db_session, fake_clock).get_for_user(user.id, category.id)

    async def test_missing_category_is_reported(self, db_session, fake_clock, user_factory):
        user = await user_factory()

        with pytest.raises(NotFoundError):
            await CategoriesService(db_session, fake_clock).get_for_user(user.id, 10**9)


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
