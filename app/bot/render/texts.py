"""Every user-facing string lives here. Handlers never hold literals."""

from typing import Any, Final

Lang = str
DEFAULT_LANG: Final = "ru"
SUPPORTED_LANGS: Final = ("ru", "en")

TEXTS: Final[dict[str, dict[Lang, str]]] = {
    "start.greeting": {
        "ru": "Привет, {name}. Я напоминаю о делах и жду реакции: готово, отложить, пропустить.",
        "en": "Hi {name}. I remind you about things and wait for a reaction: done, snooze, skip.",
    },
    "start.ask_timezone": {
        "ru": (
            "В какой таймзоне ты живёшь? Выбери из списка "
            "или пришли IANA-имя, например Europe/Moscow."
        ),
        "en": (
            "Which timezone do you live in? Pick one "
            "or send an IANA name, for example Europe/Moscow."
        ),
    },
    "start.timezone_saved": {
        "ru": "Таймзона сохранена: {timezone}.",
        "en": "Timezone saved: {timezone}.",
    },
    "start.timezone_unknown": {
        "ru": "Не знаю такую таймзону. Пришли IANA-имя, например Europe/Berlin.",
        "en": "Unknown timezone. Send an IANA name, for example Europe/Berlin.",
    },
    "start.timezone_manual": {
        "ru": "Пришли IANA-имя таймзоны, например Asia/Tbilisi.",
        "en": "Send an IANA timezone name, for example Asia/Tbilisi.",
    },
    "start.welcome_back": {
        "ru": "С возвращением, {name}. Вот текущие настройки.",
        "en": "Welcome back, {name}. Here are your current settings.",
    },
    "settings.title": {
        "ru": "Настройки\nТаймзона: {timezone}\nЯзык: {language}\nТихие часы: {quiet}",
        "en": "Settings\nTimezone: {timezone}\nLanguage: {language}\nQuiet hours: {quiet}",
    },
    "settings.quiet_off": {"ru": "выключены", "en": "off"},
    "settings.quiet_value": {"ru": "{start}-{end}", "en": "{start}-{end}"},
    "settings.pick_timezone": {
        "ru": "Выбери таймзону или пришли IANA-имя.",
        "en": "Pick a timezone or send an IANA name.",
    },
    "settings.pick_language": {"ru": "Выбери язык.", "en": "Pick a language."},
    "settings.pick_quiet": {
        "ru": "Тихие часы: {quiet}. В тишине доставка сдвигается на конец интервала.",
        "en": "Quiet hours: {quiet}. Inside them delivery moves to the end of the interval.",
    },
    "settings.pick_quiet_start": {
        "ru": "С какого времени начинается тишина?",
        "en": "When do quiet hours start?",
    },
    "settings.pick_quiet_end": {
        "ru": "До какого времени длится тишина?",
        "en": "When do quiet hours end?",
    },
    "settings.quiet_saved": {
        "ru": "Тихие часы: {start}-{end}.",
        "en": "Quiet hours: {start}-{end}.",
    },
    "settings.quiet_cleared": {"ru": "Тихие часы выключены.", "en": "Quiet hours are off."},
    "settings.quiet_equal": {
        "ru": "Начало и конец тишины совпадают. Выбери разные времена.",
        "en": "Quiet hours start and end match. Pick different times.",
    },
    "settings.language_saved": {"ru": "Язык: {language}.", "en": "Language: {language}."},
    "settings.time_manual": {
        "ru": "Пришли время в формате HH:MM, например 23:00.",
        "en": "Send a time as HH:MM, for example 23:00.",
    },
    "settings.time_invalid": {
        "ru": "Не понял время. Формат HH:MM, например 23:00.",
        "en": "Unclear time. Use HH:MM, for example 23:00.",
    },
    "settings.saved": {"ru": "Сохранено", "en": "Saved"},
    "lang.ru": {"ru": "Русский", "en": "Russian"},
    "lang.en": {"ru": "Английский", "en": "English"},
    "categories.title": {"ru": "Категории", "en": "Categories"},
    "categories.empty": {"ru": "Категорий пока нет.", "en": "No categories yet."},
    "wizard.pick_category": {"ru": "Выбери категорию.", "en": "Pick a category."},
    "wizard.ask_title": {
        "ru": "Как назвать напоминание?",
        "en": "What should the reminder be called?",
    },
    "wizard.ask_interval": {
        "ru": "Как часто напоминать?",
        "en": "How often should I remind you?",
    },
    "wizard.ask_window": {
        "ru": "В какое окно дня напоминать?",
        "en": "During which part of the day?",
    },
    "wizard.confirm": {
        "ru": (
            "Создать напоминание «{title}» каждые {every_minutes} мин "
            "с {window_start} до {window_end}?"
        ),
        "en": (
            "Create reminder «{title}» every {every_minutes} min "
            "from {window_start} to {window_end}?"
        ),
    },
    "wizard.created": {"ru": "Напоминание создано.", "en": "Reminder created."},
    "wizard.cancelled": {"ru": "Отменено.", "en": "Cancelled."},
    "wizard.title_too_long": {
        "ru": "Слишком длинное название, максимум 120 символов.",
        "en": "Title is too long, 120 characters max.",
    },
    "reminder.message": {
        "ru": "{emoji} <b>{title}</b>\n{time}",
        "en": "{emoji} <b>{title}</b>\n{time}",
    },
    "reminder.card": {
        "ru": "{emoji} <b>{title}</b>\nСтатус: {status}\nБлижайшее: {next_fire}",
        "en": "{emoji} <b>{title}</b>\nStatus: {status}\nNext: {next_fire}",
    },
    "reminder.no_next_fire": {"ru": "не запланировано", "en": "not scheduled"},
    "list.title": {"ru": "Напоминания ({total})", "en": "Reminders ({total})"},
    "list.empty": {"ru": "Напоминаний пока нет.", "en": "No reminders yet."},
    "list.item": {
        "ru": "{index}. {emoji} {title} — {next_fire}",
        "en": "{index}. {emoji} {title} — {next_fire}",
    },
    "stats.title": {"ru": "Статистика", "en": "Statistics"},
    "stats.body": {
        "ru": (
            "Серия: {streak} дн. (лучшая {longest})\n"
            "7 дней: {rate7}% ({done7} из {total7})\n"
            "30 дней: {rate30}% ({done30} из {total30})"
        ),
        "en": (
            "Streak: {streak} d (best {longest})\n"
            "7 days: {rate7}% ({done7} of {total7})\n"
            "30 days: {rate30}% ({done30} of {total30})"
        ),
    },
    "react.done": {"ru": "Готово", "en": "Done"},
    "react.snoozed": {"ru": "Отложено до {until}", "en": "Snoozed until {until}"},
    "react.skipped": {"ru": "Пропущено", "en": "Skipped"},
    "react.already": {"ru": "Уже отмечено", "en": "Already handled"},
    "react.expired": {"ru": "Срок истёк", "en": "Expired"},
    "btn.done": {"ru": "Готово", "en": "Done"},
    "btn.snooze": {"ru": "Отложить {minutes} мин", "en": "Snooze {minutes} min"},
    "btn.skip": {"ru": "Пропустить", "en": "Skip"},
    "btn.prev": {"ru": "‹", "en": "‹"},
    "btn.next": {"ru": "›", "en": "›"},
    "btn.yes": {"ru": "Да", "en": "Yes"},
    "btn.cancel": {"ru": "Отмена", "en": "Cancel"},
    "btn.new_category": {"ru": "Новая категория", "en": "New category"},
    "btn.manual_input": {"ru": "Ввести вручную", "en": "Enter manually"},
    "btn.ready": {"ru": "Готово", "en": "Done"},
    "btn.back": {"ru": "‹ Назад", "en": "‹ Back"},
    "btn.timezone": {"ru": "Таймзона", "en": "Timezone"},
    "btn.language": {"ru": "Язык", "en": "Language"},
    "btn.quiet": {"ru": "Тихие часы", "en": "Quiet hours"},
    "btn.quiet_set": {"ru": "Задать", "en": "Set"},
    "btn.quiet_off": {"ru": "Выключить", "en": "Turn off"},
    "status.active": {"ru": "активно", "en": "active"},
    "status.paused": {"ru": "на паузе", "en": "paused"},
    "status.archived": {"ru": "в архиве", "en": "archived"},
    "error.generic": {
        "ru": "Что-то пошло не так. Попробуй ещё раз.",
        "en": "Something went wrong. Try again.",
    },
    "error.not_found": {"ru": "Не нашёл такую запись.", "en": "Not found."},
}

WEEKDAY_LABELS: Final[dict[Lang, tuple[str, ...]]] = {
    "ru": ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"),
    "en": ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
}


def T(key: str, lang: Lang = DEFAULT_LANG, **kwargs: Any) -> str:
    """Resolve a user-facing string. An unknown key is a bug, not a fallback."""
    try:
        variants = TEXTS[key]
    except KeyError as exc:
        raise KeyError(f"unknown text key: {key}") from exc
    template = variants.get(lang) or variants[DEFAULT_LANG]
    return template.format(**kwargs) if kwargs else template
