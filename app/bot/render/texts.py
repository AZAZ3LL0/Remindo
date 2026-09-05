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
        "ru": (
            "Настройки\nТаймзона: {timezone}\nЯзык: {language}\n"
            "Тихие часы: {quiet}\nНедельный дайджест: {digest}"
        ),
        "en": (
            "Settings\nTimezone: {timezone}\nLanguage: {language}\n"
            "Quiet hours: {quiet}\nWeekly digest: {digest}"
        ),
    },
    "settings.digest_on": {"ru": "включён", "en": "on"},
    "settings.digest_off": {"ru": "выключен", "en": "off"},
    "settings.digest_saved": {
        "ru": "Недельный дайджест: {state}.",
        "en": "Weekly digest: {state}.",
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
    "categories.item": {"ru": "{index}. {emoji} {title}", "en": "{index}. {emoji} {title}"},
    "categories.card": {
        "ru": "{emoji} <b>{title}</b>\nКод: {code}\nТип: {kind}\nНапоминаний: {reminders}",
        "en": "{emoji} <b>{title}</b>\nCode: {code}\nKind: {kind}\nReminders: {reminders}",
    },
    "categories.kind_system": {"ru": "системная", "en": "system"},
    "categories.kind_own": {"ru": "своя", "en": "yours"},
    "categories.ask_title": {
        "ru": "Как назвать категорию?",
        "en": "What should the category be called?",
    },
    "categories.ask_emoji": {
        "ru": "Выбери эмодзи или пришли своё.",
        "en": "Pick an emoji or send your own.",
    },
    "categories.emoji_manual": {"ru": "Пришли одно эмодзи.", "en": "Send a single emoji."},
    "categories.created": {
        "ru": "Категория {emoji} {title} создана.",
        "en": "Category {emoji} {title} created.",
    },
    "categories.ask_new_title": {
        "ru": "Новое название категории?",
        "en": "New title for the category?",
    },
    "categories.renamed": {
        "ru": "Категория переименована: {title}.",
        "en": "Category renamed: {title}.",
    },
    "categories.confirm_archive": {
        "ru": "Убрать категорию {title} в архив? Напоминания в ней останутся.",
        "en": "Archive category {title}? Its reminders stay where they are.",
    },
    "categories.archived": {
        "ru": "Категория {title} в архиве.",
        "en": "Category {title} archived.",
    },
    "categories.already_archived": {
        "ru": "Категория уже в архиве.",
        "en": "The category is already archived.",
    },
    "categories.in_use": {
        "ru": "В категории есть незавершённые напоминания. Сначала разберись с ними.",
        "en": "The category still has live reminders. Deal with them first.",
    },
    "categories.system_readonly": {
        "ru": "Системную категорию менять нельзя.",
        "en": "A system category is read-only.",
    },
    "categories.title_invalid": {
        "ru": "Название от 1 до 64 символов.",
        "en": "Title must be 1 to 64 characters.",
    },
    "categories.emoji_invalid": {
        "ru": "Нужно ровно одно эмодзи.",
        "en": "Exactly one emoji is required.",
    },
    "categories.duplicate": {
        "ru": "Категория с таким названием уже есть.",
        "en": "A category with this title already exists.",
    },
    "categories.cancelled": {"ru": "Отменено.", "en": "Cancelled."},
    "wizard.pick_category": {"ru": "Выбери категорию.", "en": "Pick a category."},
    "wizard.ask_title": {
        "ru": "Как назвать напоминание?",
        "en": "What should the reminder be called?",
    },
    "wizard.pick_kind": {
        "ru": "Какое расписание?",
        "en": "Which schedule?",
    },
    "wizard.ask_interval": {
        "ru": "Как часто напоминать?",
        "en": "How often should I remind you?",
    },
    "wizard.ask_window": {
        "ru": "В какое окно дня напоминать?",
        "en": "During which part of the day?",
    },
    "wizard.ask_date": {"ru": "На какой день?", "en": "Which day?"},
    "wizard.ask_at": {"ru": "Во сколько напомнить?", "en": "At what time?"},
    "wizard.ask_times": {
        "ru": "Во сколько напоминать? Выбрано: {times}",
        "en": "At what times? Selected: {times}",
    },
    "wizard.times_none": {"ru": "пока ничего", "en": "nothing yet"},
    "wizard.times_empty": {
        "ru": "Выбери хотя бы одно время.",
        "en": "Pick at least one time.",
    },
    "wizard.times_full": {
        "ru": "Больше {limit} времён в день не бывает.",
        "en": "No more than {limit} times a day.",
    },
    "wizard.ask_weekdays": {
        "ru": "По каким дням недели? Выбрано: {weekdays}",
        "en": "On which weekdays? Selected: {weekdays}",
    },
    "wizard.weekdays_none": {"ru": "пока ничего", "en": "nothing yet"},
    "wizard.weekdays_empty": {
        "ru": "Выбери хотя бы один день недели.",
        "en": "Pick at least one weekday.",
    },
    "wizard.ask_mdays": {
        "ru": "По каким числам месяца? Выбрано: {days}",
        "en": "On which days of the month? Selected: {days}",
    },
    "wizard.mdays_none": {"ru": "пока ничего", "en": "nothing yet"},
    "wizard.mdays_empty": {
        "ru": "Выбери хотя бы одно число.",
        "en": "Pick at least one day of the month.",
    },
    "wizard.ask_missing_day": {
        "ru": "А если в месяце нет такого числа?",
        "en": "And in a month that has no such day?",
    },
    "wizard.interval_manual": {
        "ru": "Пришли интервал в минутах, например 90.",
        "en": "Send the interval in minutes, for example 90.",
    },
    "wizard.interval_invalid": {
        "ru": "Интервал от {minimum} до {maximum} минут.",
        "en": "Interval must be {minimum} to {maximum} minutes.",
    },
    "wizard.window_manual": {
        "ru": "Пришли окно в формате HH:MM-HH:MM, например 09:00-21:00.",
        "en": "Send a window as HH:MM-HH:MM, for example 09:00-21:00.",
    },
    "wizard.window_invalid": {
        "ru": "Не понял окно. Формат HH:MM-HH:MM, например 09:00-21:00.",
        "en": "Unclear window. Use HH:MM-HH:MM, for example 09:00-21:00.",
    },
    "wizard.date_manual": {
        "ru": "Пришли дату в формате ГГГГ-ММ-ДД, например 2026-09-01.",
        "en": "Send a date as YYYY-MM-DD, for example 2026-09-01.",
    },
    "wizard.date_invalid": {
        "ru": "Не понял дату. Формат ГГГГ-ММ-ДД, от сегодня и не дальше чем на год.",
        "en": "Unclear date. Use YYYY-MM-DD, from today and no more than a year ahead.",
    },
    "wizard.time_manual": {
        "ru": "Пришли время в формате HH:MM, например 07:30.",
        "en": "Send a time as HH:MM, for example 07:30.",
    },
    "wizard.time_invalid": {
        "ru": "Не понял время. Формат HH:MM, например 07:30.",
        "en": "Unclear time. Use HH:MM, for example 07:30.",
    },
    "wizard.past_moment": {
        "ru": "Этот момент уже прошёл. Выбери время в будущем.",
        "en": "That moment has passed. Pick a time in the future.",
    },
    "wizard.confirm_once": {
        "ru": "Создать напоминание «{title}» на {at}?",
        "en": "Create reminder «{title}» for {at}?",
    },
    "wizard.confirm_daily": {
        "ru": "Создать напоминание «{title}» каждый день в {times}?",
        "en": "Create reminder «{title}» every day at {times}?",
    },
    "wizard.confirm_interval": {
        "ru": (
            "Создать напоминание «{title}» каждые {every_minutes} мин "
            "с {window_start} до {window_end}?"
        ),
        "en": (
            "Create reminder «{title}» every {every_minutes} min "
            "from {window_start} to {window_end}?"
        ),
    },
    "wizard.confirm_weekly": {
        "ru": "Создать напоминание «{title}» по {weekdays} в {times}?",
        "en": "Create reminder «{title}» on {weekdays} at {times}?",
    },
    "wizard.confirm_monthly": {
        "ru": "Создать напоминание «{title}» {days} числа в {times}? Короткий месяц: {missing}.",
        "en": "Create reminder «{title}» on day {days} at {times}? Short month: {missing}.",
    },
    "missing.last_day": {"ru": "последний день", "en": "the last day"},
    "missing.skip": {"ru": "пропустить", "en": "skip"},
    "wizard.created": {"ru": "Напоминание создано.", "en": "Reminder created."},
    "wizard.cancelled": {"ru": "Отменено.", "en": "Cancelled."},
    "wizard.title_invalid": {
        "ru": "Название от 1 до 120 символов.",
        "en": "Title must be 1 to 120 characters.",
    },
    "reminder.message": {
        "ru": "{emoji} <b>{title}</b>\n{time}",
        "en": "{emoji} <b>{title}</b>\n{time}",
    },
    # The card is where the user decides what to change, so it spells out the
    # schedule, the note and the shared access as well (tech.md 21.7, 22.8).
    "reminder.card": {
        "ru": (
            "{emoji} <b>{title}</b>\nСтатус: {status}\n"
            "Расписание: {schedule}\nБлижайшее: {next_fire}{shared}{note}"
        ),
        "en": (
            "{emoji} <b>{title}</b>\nStatus: {status}\n"
            "Schedule: {schedule}\nNext: {next_fire}{shared}{note}"
        ),
    },
    "reminder.note": {"ru": "\nЗаметка: {note}", "en": "\nNote: {note}"},
    "reminder.shared": {
        "ru": "\nПолучателей кроме тебя: {count}",
        "en": "\nRecipients besides you: {count}",
    },
    "reminder.schedule": {
        "ru": "{summary}, отложить на {snooze} мин, повтор: {repeat}",
        "en": "{summary}, snooze {snooze} min, repeat: {repeat}",
    },
    # One line per schedule kind, for the card. The wizard's confirmations
    # cannot be reused: they ask a question, the card states a fact.
    "schedule.once": {"ru": "один раз, {at}", "en": "once, {at}"},
    "schedule.daily": {"ru": "каждый день в {times}", "en": "every day at {times}"},
    "schedule.weekly": {"ru": "{weekdays} в {times}", "en": "{weekdays} at {times}"},
    "schedule.monthly": {
        "ru": "{days} числа в {times}, короткий месяц: {missing}",
        "en": "on the {days} at {times}, short month: {missing}",
    },
    "schedule.interval": {
        "ru": "каждые {every_minutes} мин, {window_start}-{window_end}",
        "en": "every {every_minutes} min, {window_start}-{window_end}",
    },
    "reminder.repeat_off": {"ru": "выключен", "en": "off"},
    "reminder.repeat_on": {"ru": "через {minutes} мин", "en": "after {minutes} min"},
    "reminder.paused": {"ru": "Напоминание на паузе.", "en": "Reminder paused."},
    "reminder.resumed": {"ru": "Напоминание снова активно.", "en": "Reminder is active again."},
    "reminder.confirm_delete": {
        "ru": "Удалить «{title}» вместе со всей историей?",
        "en": "Delete “{title}” together with its whole history?",
    },
    "reminder.deleted": {"ru": "Напоминание удалено.", "en": "Reminder deleted."},
    "reminder.archived_readonly": {
        "ru": "Напоминание в архиве, его уже не изменить.",
        "en": "The reminder is archived and cannot be changed.",
    },
    "reminder.no_next_fire": {"ru": "не запланировано", "en": "not scheduled"},
    "list.title": {"ru": "Напоминания ({total})", "en": "Reminders ({total})"},
    "list.empty": {"ru": "Напоминаний пока нет.", "en": "No reminders yet."},
    "list.item": {
        "ru": "{index}. {mark}{emoji} {title} — {next_fire}",
        "en": "{index}. {mark}{emoji} {title} — {next_fire}",
    },
    "list.paused_mark": {"ru": "⏸ ", "en": "⏸ "},
    "list.filter": {"ru": "Фильтр: {title}", "en": "Filter: {title}"},
    "list.filter_all": {"ru": "все категории", "en": "all categories"},
    # Shared access (tech.md 22.8).
    "share.menu": {
        "ru": "Доступ к «{title}».\n{recipients}",
        "en": "Access to “{title}”.\n{recipients}",
    },
    "share.recipients": {"ru": "Получатели:\n{items}", "en": "Recipients:\n{items}"},
    "share.recipients_none": {
        "ru": "Пока никто, кроме тебя.",
        "en": "Nobody but you so far.",
    },
    "share.recipient_item": {"ru": "• {mark}{name}", "en": "• {mark}{name}"},
    "share.pending_mark": {"ru": "⏳ ", "en": "⏳ "},
    "share.owner": {"ru": "ты", "en": "you"},
    "share.unknown_user": {"ru": "без имени", "en": "no name"},
    "share.invite_link": {
        "ru": "Ссылка живёт до {until}. Отдай её тому, кого зовёшь:\n{link}",
        "en": "The link lives until {until}. Hand it to whoever you are inviting:\n{link}",
    },
    "share.invite_revoked": {
        "ru": "Ссылка отозвана. По ней больше не присоединиться.",
        "en": "The link is revoked. Nobody can join through it any more.",
    },
    "share.no_invite": {"ru": "Живой ссылки нет.", "en": "There is no live link."},
    "share.link_invalid": {
        "ru": "Это не похоже на приглашение.",
        "en": "That does not look like an invitation.",
    },
    "share.link_unknown": {
        "ru": "Такого приглашения нет.",
        "en": "No such invitation.",
    },
    "share.link_dead": {
        "ru": "Приглашение отозвано или просрочено. Попроси новую ссылку.",
        "en": "The invitation is revoked or expired. Ask for a new link.",
    },
    "share.own_invite": {
        "ru": "Это твоё собственное напоминание.",
        "en": "This is your own reminder.",
    },
    "share.already_in": {
        "ru": "Ты уже получаешь это напоминание.",
        "en": "You already receive this reminder.",
    },
    "share.full": {
        "ru": "У напоминания уже {maximum} получателей, больше не поместится.",
        "en": "The reminder already has {maximum} recipients and cannot take more.",
    },
    "share.offer": {
        "ru": "{owner} зовёт тебя получать это напоминание.",
        "en": "{owner} invites you to receive this reminder.",
    },
    "share.accepted": {
        "ru": "Готово, напоминание будет приходить и тебе.",
        "en": "Done, the reminder will reach you too.",
    },
    "share.declined": {"ru": "Приглашение отклонено.", "en": "Invitation declined."},
    "share.confirm_leave": {
        "ru": "Отписаться от «{title}»?",
        "en": "Unsubscribe from “{title}”?",
    },
    "share.left": {
        "ru": "Отписался. Это напоминание больше не придёт.",
        "en": "Unsubscribed. This reminder will not reach you again.",
    },
    "share.list_title": {"ru": "Общие напоминания ({total})", "en": "Shared reminders ({total})"},
    "share.list_empty": {
        "ru": "Тебя пока никуда не звали.",
        "en": "Nobody has invited you anywhere yet.",
    },
    "share.list_item": {
        "ru": "{index}. {mark}{emoji} {title} — от {owner}",
        "en": "{index}. {mark}{emoji} {title} — from {owner}",
    },
    "share.card": {
        "ru": "{emoji} <b>{title}</b>\nОт: {owner}\nРасписание: {schedule}\nБлижайшее: {next_fire}",
        "en": "{emoji} <b>{title}</b>\nFrom: {owner}\nSchedule: {schedule}\nNext: {next_fire}",
    },
    "edit.menu": {"ru": "Что меняем?", "en": "What are we changing?"},
    "edit.ask_title": {"ru": "Пришли новое название.", "en": "Send the new title."},
    "edit.ask_note": {
        "ru": "Пришли заметку или очисти её кнопкой.",
        "en": "Send a note, or clear it with the button.",
    },
    "edit.ask_category": {"ru": "Выбери новую категорию.", "en": "Pick the new category."},
    "edit.ask_snooze": {
        "ru": "На сколько минут откладывать?",
        "en": "How many minutes should a snooze last?",
    },
    "edit.ask_repeat": {
        "ru": "Через сколько минут повторять без реакции?",
        "en": "After how many minutes should an unanswered reminder repeat?",
    },
    "edit.pick_kind": {"ru": "Выбери новое расписание.", "en": "Pick the new schedule."},
    "edit.saved": {"ru": "Изменения сохранены.", "en": "Changes saved."},
    "edit.snooze_invalid": {
        "ru": "Шаг должен быть числом минут от {minimum} до {maximum}.",
        "en": "The step must be a number of minutes between {minimum} and {maximum}.",
    },
    "edit.repeat_invalid": {
        "ru": "Повтор должен быть числом минут от {minimum} до {maximum}.",
        "en": "The repeat must be a number of minutes between {minimum} and {maximum}.",
    },
    "edit.note_invalid": {
        "ru": "Заметка не длиннее {maximum} символов.",
        "en": "A note is at most {maximum} characters.",
    },
    "edit.repeat_off": {"ru": "Автоповтор выключен.", "en": "The automatic repeat is off."},
    "edit.cancelled": {"ru": "Изменения отменены.", "en": "Changes cancelled."},
    "today.title": {"ru": "Сегодня ({total})", "en": "Today ({total})"},
    "today.empty": {"ru": "На сегодня ничего нет.", "en": "Nothing for today."},
    "today.item": {
        "ru": "{time} {mark} {emoji} {title}",
        "en": "{time} {mark} {emoji} {title}",
    },
    "today.mark_pending": {"ru": "•", "en": "•"},
    "today.mark_done": {"ru": "✓", "en": "✓"},
    "today.mark_skipped": {"ru": "—", "en": "—"},
    "today.mark_missed": {"ru": "×", "en": "×"},
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
    "stats.by_category": {"ru": "По категориям\n{items}", "en": "By category\n{items}"},
    "stats.category_item": {
        "ru": "{emoji} {title} — серия {streak} дн., 7 дней {rate7}%",
        "en": "{emoji} {title} — streak {streak} d, 7 days {rate7}%",
    },
    "stats.category_none": {
        "ru": "Реакций пока нет, поэтому и разбивки нет.",
        "en": "No reactions yet, so there is no breakdown either.",
    },
    "stats.card": {"ru": "Статистика: {emoji} {title}", "en": "Statistics: {emoji} {title}"},
    "digest.title": {
        "ru": "Итоги недели {start} — {end}",
        "en": "Your week: {start} to {end}",
    },
    "digest.body": {
        "ru": "Выполнено {done} из {total} ({rate}%)\nСерия: {streak} дн.",
        "en": "Done {done} of {total} ({rate}%)\nStreak: {streak} d",
    },
    "digest.category_item": {
        "ru": "{emoji} {title} — {done} из {total}",
        "en": "{emoji} {title} — {done} of {total}",
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
    "btn.kind_once": {"ru": "Один раз", "en": "Once"},
    "btn.kind_daily": {"ru": "Каждый день", "en": "Every day"},
    "btn.kind_weekly": {"ru": "По дням недели", "en": "By weekday"},
    "btn.kind_monthly": {"ru": "По числам месяца", "en": "By month day"},
    "btn.kind_interval": {"ru": "По интервалу", "en": "By interval"},
    "btn.missing_last_day": {"ru": "Последний день", "en": "Last day"},
    "btn.missing_skip": {"ru": "Пропустить месяц", "en": "Skip the month"},
    "btn.today": {"ru": "Сегодня", "en": "Today"},
    "btn.tomorrow": {"ru": "Завтра", "en": "Tomorrow"},
    "btn.back": {"ru": "‹ Назад", "en": "‹ Back"},
    "btn.rename": {"ru": "Переименовать", "en": "Rename"},
    "btn.archive": {"ru": "В архив", "en": "Archive"},
    "btn.filter": {"ru": "Фильтр", "en": "Filter"},
    "btn.all_categories": {"ru": "Все категории", "en": "All categories"},
    "btn.pause": {"ru": "Пауза", "en": "Pause"},
    "btn.resume": {"ru": "Возобновить", "en": "Resume"},
    "btn.edit": {"ru": "Изменить", "en": "Edit"},
    "btn.delete": {"ru": "Удалить", "en": "Delete"},
    "btn.to_list": {"ru": "‹ К списку", "en": "‹ To the list"},
    "btn.edit_title": {"ru": "Название", "en": "Title"},
    "btn.edit_note": {"ru": "Заметка", "en": "Note"},
    "btn.edit_category": {"ru": "Категория", "en": "Category"},
    "btn.edit_schedule": {"ru": "Расписание", "en": "Schedule"},
    "btn.edit_snooze": {"ru": "Отложить на", "en": "Snooze step"},
    "btn.edit_repeat": {"ru": "Автоповтор", "en": "Auto repeat"},
    "btn.repeat_off": {"ru": "Выключить", "en": "Turn off"},
    "btn.note_clear": {"ru": "Очистить", "en": "Clear"},
    "btn.share": {"ru": "Доступ", "en": "Access"},
    "btn.invite": {"ru": "Пригласить", "en": "Invite"},
    "btn.revoke": {"ru": "Отозвать ссылку", "en": "Revoke the link"},
    "btn.accept": {"ru": "Принять", "en": "Accept"},
    "btn.decline": {"ru": "Отклонить", "en": "Decline"},
    "btn.leave": {"ru": "Отписаться", "en": "Unsubscribe"},
    "btn.to_shared": {"ru": "‹ К общим", "en": "‹ To shared"},
    "btn.timezone": {"ru": "Таймзона", "en": "Timezone"},
    "btn.language": {"ru": "Язык", "en": "Language"},
    "btn.quiet": {"ru": "Тихие часы", "en": "Quiet hours"},
    "btn.quiet_set": {"ru": "Задать", "en": "Set"},
    "btn.quiet_off": {"ru": "Выключить", "en": "Turn off"},
    "btn.digest_on": {"ru": "Включить дайджест", "en": "Turn the digest on"},
    "btn.digest_off": {"ru": "Выключить дайджест", "en": "Turn the digest off"},
    "btn.stats_all": {"ru": "‹ Ко всем категориям", "en": "‹ To all categories"},
    "status.active": {"ru": "активно", "en": "active"},
    "status.paused": {"ru": "на паузе", "en": "paused"},
    "status.archived": {"ru": "в архиве", "en": "archived"},
    # Operator-facing, but strings sent to Telegram live here without
    # exception (tech.md 24.8): a second catalogue would drift from the first.
    "ops.alert_lag": {
        "ru": "Доставка отстаёт: лаг {lag} мин, в очереди {queue}, ошибок {errors}%.",
        "en": "Delivery is falling behind: lag {lag} min, {queue} queued, {errors}% failing.",
    },
    "ops.alert_cleared": {
        "ru": "Доставка догнала: лаг {lag} мин, в очереди {queue}, ошибок {errors}%.",
        "en": "Delivery caught up: lag {lag} min, {queue} queued, {errors}% failing.",
    },
    # The help screen carries no placeholders: the command table is glued on
    # from cmd.* rather than formatted in, so a ninth command edits one place
    # instead of two (tech.md 25.6).
    "help.screen": {
        "ru": (
            "Я напоминаю о делах и жду ответа.\n\n"
            "Заводишь дело и расписание, я пишу в срок, а ты жмёшь "
            "<b>Готово</b>, <b>Отложить</b> или <b>Пропустить</b>. "
            "По этим нажатиям и считается статистика: серия дней подряд "
            "и доля выполненного.\n\n"
            "<b>Команды</b>"
        ),
        "en": (
            "I remind you about things and wait for an answer.\n\n"
            "You set up a thing and a schedule, I write when it is due, and you "
            "press <b>Done</b>, <b>Snooze</b> or <b>Skip</b>. Those presses are "
            "what the statistics are counted from: the streak of days in a row "
            "and the share completed.\n\n"
            "<b>Commands</b>"
        ),
    },
    "help.unknown": {
        "ru": "Не понял. Вот что я умею:",
        "en": "I did not get that. Here is what I can do:",
    },
    "cmd.new": {"ru": "Новое напоминание", "en": "New reminder"},
    "cmd.list": {"ru": "Мои напоминания", "en": "My reminders"},
    "cmd.today": {"ru": "Что сегодня", "en": "What is due today"},
    "cmd.categories": {"ru": "Категории", "en": "Categories"},
    "cmd.stats": {"ru": "Статистика", "en": "Statistics"},
    "cmd.shared": {"ru": "Общие напоминания", "en": "Shared reminders"},
    "cmd.settings": {"ru": "Таймзона, язык, тихие часы", "en": "Timezone, language, quiet hours"},
    "cmd.help": {"ru": "Что я умею", "en": "What I can do"},
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
