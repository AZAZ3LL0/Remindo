# tech.md — ядро проекта Reminder Bot

**Версия ядра: v13**

Changelog:
- `v1` — первичная фиксация: стек, структура, схема БД, контракты расписаний и воркеров, протоколы гейтвеев, стратегия тестов, дорожная карта.
- `v2` — §0 состав команды и совмещение ролей; §12.2 авторство коммитов и PR (git identity, запрет посторонних трейлеров).
- `v3` — §16 контракт слайса S1: enum `Language`, список `POPULAR_TIMEZONES`, CallbackData-фабрика `SetCb` (префикс `s`), публичные `parse_hhmm`/`format_hhmm`, клавиатуры настроек, ключи текстов, три новых модуля слайса.
- `v5` — §18 контракт слайса S3: атомы `WizCb` для типа расписания, даты и времени, лимиты напоминания и горизонт мастера в `domain/contracts.py`, публичные `parse_local_date`/`format_local_date` и `TIMES_MAX_LENGTH`, клавиатуры мастера, ключи текстов, два переименованных ключа `wizard.*`, три новых модуля слайса.
- `v6` — §19 контракт слайса S7: атомы `WizCb` для дней недели, чисел месяца, правила пропущенного дня и ручного ввода интервала и окна, пара `pack_window`/`unpack_window` в `bot/callbacks.py`, именованные лимиты расписаний в `domain/schedules.py`, пять клавиатур мастера, ключи текстов, три состояния FSM, полный набор DST-инвариантов.
- `v7` — §20 контракт слайса S8: тихие часы на каждом пути доставки (правки строк §7.1, §7.3 и §7.4), значение `QuietHours` в `domain/quiet_hours.py`, чистый модуль `domain/sweeping.py`, отображение получателя `services/recipients.py`, бюджет повторов на occurrence, новая сигнатура `decide_reaction`, два новых модуля слайса.
- `v8` — §21 контракт слайса S9: CallbackData-фабрики `ListCb` (префикс `l`) и `EditCb` (префикс `e`), атомы `WizCb` для шага «отложить», автоповтора и заметки, параметр `nav` у `paginated_kb`, снятие незапущенных occurrences при паузе и правке расписания, границы правки напоминания, лимиты `SNOOZE_*` и `REPEAT_*` в `domain/contracts.py`, семь клавиатур, ключи текстов, два плейсхолдера у `reminder.card`, публичные `parse_user_snooze`, `parse_user_repeat` и `local_day_bounds`, четыре новых модуля слайса.
- `v9` — §22 контракт слайса S10: таблица `reminder_invites`, чистый модуль `domain/sharing.py` с токеном и deep-link, CallbackData-фабрика `ShareCb` (префикс `i`), значение `shared` у `PageCb.scope`, действие `leave` у `confirm_kb`, лимиты приглашения и наблюдателей в `domain/contracts.py`, `InviteExpiredError` и `RecipientLimitError`, достройка и снятие доставок при принятии и отписке, четыре клавиатуры, ключи текстов, плейсхолдер `{shared}` у `reminder.card`, `BOT_USERNAME` в конфигурации, семь новых модулей слайса.
- `v10` — §23 контракт слайса S11: правила счёта статистики по журналу, разбивка `by_category` и `CategoryStats` в `domain/stats.py`, CallbackData-фабрика `StatCb` (префикс `t`), джоб `digest.send` и четвёртый цикл воркера, чистый модуль `domain/digest.py`, колонки `users.digest_enabled` и `users.digest_sent_at`, значение `digest` у `SetCb.field`, переменные `DIGEST_*` в конфигурации, две клавиатуры, ключи текстов, плейсхолдер `{digest}` у `settings.title`, четыре новых модуля слайса.
- `v11` — §24 контракт слайса S12: healthcheck-эндпоинт и экспозиция метрик воркера, `HealthStatus` в `domain/contracts.py`, джоб `ops.monitor` и пятый цикл воркера, чистый модуль `domain/ops.py`, снимок очереди в `DeliveriesRepository`, порог алерта на переходе, переменные `HEALTH_*`, `ALERT_LAG_MINUTES`, `METRICS_WINDOW_MINUTES` и `BACKUP_*` в конфигурации, ключи текстов, `scripts/backup.sh`, ротация логов и healthcheck воркера в compose, четыре новых модуля слайса.
- `v13` — §26 контракт главного меню: постоянная reply-клавиатура из того же списка команд, подписи `btn.menu_*`, индекс подписей по всем локалям, роутер меню первым, навигация снимает состояние мастера, текстовые шаги FSM перестают принимать команды за текст, фильтр `NOT_A_COMMAND`, три новых модуля.
- `v12` — §25 контракт справки и меню команд: единый список команд `app/bot/commands.py` с исключением `MENU_EXEMPT_COMMANDS`, `BotCommandSpec` и `set_commands` в протоколе `BotGateway`, валидация меню в `FakeBotGateway`, перехватчик непонятного текста последним роутером, справка вместо настроек в конце онбординга, ключи `help.*` и `cmd.*`, три новых модуля.
- `v4` — §17 контракт слайса S2: действие `confirm_archive` в `CatCb`, атомы `WizCb` для создания категории и эмодзи, лимиты категории в `domain/contracts.py`, `CategoryExistsError`, клавиатуры категорий, ключи текстов, три новых модуля слайса.

Этот файл — единственный источник истины. Любая сессия читает его первым и подчиняется дословно. Контракты не выдумываются: нет нужного типа/поля/топика — сессия останавливается и выдаёт блок `CONTRACT GAP` (формат в `CLAUDE.md`). Файл меняется только append-only, каждое изменение контракта бампает версию.

---

## 0. Команда и роли

Один человек в двух ролях: тимлид (владелец контрактов) и разработчик (исполнитель слайсов). Роли не сливаются, потому что разделение держит дисциплину контрактов, а не иерархию.

Практическое следствие совмещения:

- «апрув тимлида» на общие файлы (§11.2) означает **отдельный PR**, помеченный `contract-change`, с бампом версии ядра и обновлением changelog. Правка контракта заодно, внутри PR со слайсом, запрещена;
- сессия, работающая над слайсом, всё равно останавливается на `CONTRACT GAP` и не правит `tech.md` сама. Ядро меняется отдельной сессией в роли тимлида;
- branch protection и CODEOWNERS настраиваются даже при одном участнике: гейт держит платформа, а не память.

---

## 1. Проект

Телеграм-бот персональных напоминаний. Пользователь заводит повторяющиеся и разовые дела (таблетки, вода, зарядка, готовка, задачи, события), бот присылает напоминание в срок и ждёт реакции: выполнено, отложить, пропустить. Категории пользователь создаёт сам поверх системных пресетов. Напоминание можно адресовать не только себе, но и другим пользователям бота.

Цель: пользователь перестаёт держать рутину в голове и не пропускает её из-за забывчивости.

Не входит в проект: календарная синхронизация, оплата, веб-панель, мультиязычность сверх ru/en.

### 1.1 Ключевые продуктовые требования

- Напоминание приходит в течение 60 секунд от плановой минуты.
- Пользователь живёт в своей таймзоне; все локальные времена вводит в ней.
- Тихие часы: в интервал тишины доставка сдвигается на конец интервала, а не теряется.
- Повтор напоминания, если на него не отреагировали (настраиваемое число повторов).
- Дубль доставки допустим редко и не должен ломать статистику: повторная реакция на то же событие идемпотентна.
- Удаление пользователя удаляет его данные каскадом.

---

## 2. Стек

| Слой | Решение |
|---|---|
| Язык | Python 3.12 |
| Бот | aiogram 3.x (long polling в dev, webhook в prod по флагу) |
| БД | PostgreSQL 16 |
| ORM | SQLAlchemy 2.0 (async, `asyncpg`), typed `Mapped[...]` |
| Миграции | Alembic |
| Очередь | таблицы `occurrences` / `deliveries` в Postgres + `SELECT ... FOR UPDATE SKIP LOCKED`. Внешнего брокера нет |
| Валидация | Pydantic v2 (конфиг, JSONB-payload расписаний) |
| Таймзоны | `zoneinfo`, IANA-имена |
| Контейнеризация | Docker + docker compose |
| Тесты | pytest, pytest-asyncio, Hypothesis, `testcontainers[postgresql]` (или сервис-контейнер Postgres в CI) |
| Линт | ruff (lint + format), mypy в strict на `app/domain` и `app/services` |
| CI | GitHub Actions |
| Хостинг | тестовый VPS (автодеплой из `main`) + прод |

Запрещённые зависимости без апрува: любые ORM кроме SQLAlchemy, любые брокеры (Celery, RQ, Redis-очереди), APScheduler, `pytz`, `datetime.now()` без Clock.

---

## 3. Архитектура

Три процесса из одного образа, разные точки входа:

1. `bot` — aiogram-диспетчер, принимает апдейты, пишет в БД. Не рассылает напоминания.
2. `worker` — планировщик и доставщик. Материализует occurrences, шлёт сообщения, обрабатывает ретраи и просрочку. Не принимает апдейты.
3. `migrator` — one-shot `alembic upgrade head` в деплой-шаге.

Слои и правило зависимостей (только сверху вниз):

```
bot/ (handlers, keyboards, fsm)  ->  services/  ->  db/ (repositories, models)
worker/                          ->  services/  ->  db/
services/                        ->  domain/
domain/                          ->  ничего (stdlib + pydantic)
```

- `domain/` — чистые функции и датаклассы. Ноль IO, ноль импортов SQLAlchemy и aiogram, ноль обращений к часам напрямую. Всё, что можно проверить Hypothesis, живёт здесь.
- `services/` — сценарии использования. Оркестрируют репозитории и гейтвеи, держат транзакционные границы. Единственное место, где открывается транзакция.
- `bot/handlers/` — тонкие. Разобрать апдейт, вызвать сервис, отрендерить ответ. Бизнес-логики в хендлере нет.
- `db/repositories/` — SQL и маппинг. Возвращают ORM-модели или доменные датаклассы, не собирают бизнес-решений.

### 3.1 Структура папок

```
app/
  __init__.py
  core/
    config.py            # Pydantic Settings, единственное чтение окружения
    clock.py             # протокол Clock + SystemClock
    logging.py           # structlog-совместимый setup, JSON в prod
    di.py                # сборка зависимостей для bot и worker
  domain/
    contracts.py         # enum-ы статусов, идентификаторы джобов, версии payload
    schedules.py         # Pydantic-модели расписаний (discriminated union)
    recurrence.py        # next_occurrences(...) — чистая логика повторов
    quiet_hours.py       # apply_quiet_hours(...)
    retry.py             # backoff-политика
    stats.py             # streaks, completion rate
    errors.py            # доменные исключения
  db/
    base.py              # DeclarativeBase, naming convention для констрейнтов
    session.py           # async_sessionmaker, get_session
    models/
      user.py
      category.py
      reminder.py
      recipient.py
      occurrence.py
      delivery.py
      delivery_action.py
    repositories/
      users.py
      categories.py
      reminders.py
      occurrences.py
      deliveries.py
  gateways/
    bot_gateway.py       # Protocol BotGateway + AiogramBotGateway
    fakes.py             # FakeBotGateway, FakeClock — используются и в dev, и в тестах
  services/
    onboarding.py
    categories.py
    reminders.py
    planning.py          # материализация occurrences
    dispatching.py       # доставка и ретраи
    reactions.py         # done / snooze / skip
    stats.py
  bot/
    main.py              # entrypoint процесса bot
    middlewares/
      db.py              # сессия на апдейт
      user.py            # текущий пользователь в data
      throttle.py
    callbacks.py         # CallbackData-фабрики (контракт, см. §6)
    keyboards/
      actions.py         # клавиатура напоминания
      pagination.py
      pickers.py         # категории, время, дни недели
      confirm.py
    render/
      reminder.py
      lists.py
      stats.py
      texts.py           # все пользовательские строки, ru/en
    handlers/
      start.py
      settings.py
      categories.py
      reminders.py       # мастер создания (FSM)
      reactions.py
      lists.py
      stats.py
      errors.py
    fsm/
      reminder_wizard.py
      storage.py         # SQLAlchemy-backed FSM storage
  worker/
    main.py              # entrypoint процесса worker
    planner.py
    dispatcher.py
    reaper.py
migrations/               # Alembic
scripts/
  seed.py
tests/
  conftest.py
  unit/                   # domain, чистая логика, Hypothesis
  contract/               # payload-схемы, CallbackData, гейтвеи
  integration/            # репозитории, сервисы, воркеры на реальном Postgres
  e2e/                    # сценарий бота через FakeBotGateway
docker/
  Dockerfile
  compose.yml
  compose.ci.yml
.env.example
Makefile
```

### 3.2 Эталонный слайс

Слайс «Вода» (`water`) собирается тимлидом в скелете end-to-end: категория → мастер создания интервального напоминания → planner → dispatcher → кнопки реакции → запись в статистику → тесты всех четырёх обязательных типов.

Любой новый слайс повторяет его раскладку файлов. Сверяйся с ним, не изобретай свою.

---

## 4. Схема БД

Все временные метки — `TIMESTAMPTZ`, хранятся в UTC. Локальное время живёт только в JSONB-расписании и в поле `users.timezone`. Именование констрейнтов задаётся `naming_convention` в `db/base.py`, чтобы Alembic генерировал стабильные имена.

### 4.1 Enum-типы (Postgres native enum, определены в `domain/contracts.py`)

```
reminder_status   : active | paused | archived
schedule_kind     : once | interval | daily | weekly | monthly
occurrence_status : pending | dispatching | sent | done | skipped | expired | failed
delivery_status   : pending | sent | done | skipped | snoozed | failed | blocked
recipient_role    : owner | watcher
action_kind       : done | snooze | skip | auto_expire
```

Enum расширяется только append-only, значения не переименовываются.

### 4.2 Таблицы

**users**

| поле | тип | описание |
|---|---|---|
| id | BIGSERIAL PK | |
| tg_user_id | BIGINT NOT NULL UNIQUE | id пользователя Telegram |
| tg_chat_id | BIGINT NOT NULL | приватный чат для доставки |
| username | TEXT NULL | без `@` |
| first_name | TEXT NOT NULL DEFAULT '' | |
| language | TEXT NOT NULL DEFAULT 'ru' | `ru` \| `en` |
| timezone | TEXT NOT NULL DEFAULT 'Europe/Moscow' | IANA-имя, валидируется через `zoneinfo` |
| quiet_start | TIME NULL | локальное время начала тишины |
| quiet_end | TIME NULL | локальное время конца, может быть меньше `quiet_start` (через полночь) |
| is_blocked | BOOLEAN NOT NULL DEFAULT false | бот заблокирован пользователем |
| onboarded_at | TIMESTAMPTZ NULL | |
| created_at / updated_at | TIMESTAMPTZ NOT NULL DEFAULT now() | |

Инвариант: `quiet_start` и `quiet_end` либо оба NULL, либо оба заданы (CHECK).

**categories**

| поле | тип | описание |
|---|---|---|
| id | BIGSERIAL PK | |
| owner_id | BIGINT NULL FK users(id) ON DELETE CASCADE | NULL — системный пресет |
| code | TEXT NOT NULL | slug, `^[a-z0-9_]{2,32}$` |
| title | TEXT NOT NULL | |
| emoji | TEXT NOT NULL DEFAULT '🔔' | ровно один графемный кластер |
| is_system | BOOLEAN NOT NULL DEFAULT false | |
| sort_order | SMALLINT NOT NULL DEFAULT 100 | |
| archived_at | TIMESTAMPTZ NULL | |
| created_at | TIMESTAMPTZ NOT NULL DEFAULT now() | |

Индексы: `UNIQUE (owner_id, code) WHERE owner_id IS NOT NULL`; `UNIQUE (code) WHERE owner_id IS NULL`; `INDEX (owner_id) WHERE archived_at IS NULL`.

Системные пресеты (создаются seed-скриптом, `owner_id IS NULL`): `pills`, `water`, `workout`, `cooking`, `task`, `event`.

**reminders**

| поле | тип | описание |
|---|---|---|
| id | BIGSERIAL PK | |
| owner_id | BIGINT NOT NULL FK users(id) ON DELETE CASCADE | |
| category_id | BIGINT NOT NULL FK categories(id) ON DELETE RESTRICT | |
| title | TEXT NOT NULL | 1..120 символов |
| note | TEXT NULL | до 1000 символов |
| status | reminder_status NOT NULL DEFAULT 'active' | |
| schedule_kind | schedule_kind NOT NULL | дублирует `schedule->>'kind'`, нужен для индексов |
| schedule | JSONB NOT NULL | контракт в §5 |
| timezone | TEXT NOT NULL | снимок таймзоны владельца на момент создания |
| starts_at | TIMESTAMPTZ NOT NULL | не материализуем раньше этого момента |
| ends_at | TIMESTAMPTZ NULL | |
| max_occurrences | INTEGER NULL | лимит срабатываний за всё время |
| fired_count | INTEGER NOT NULL DEFAULT 0 | материализованных occurrences |
| snooze_minutes | SMALLINT NOT NULL DEFAULT 10 | шаг «отложить» |
| repeat_after_minutes | SMALLINT NULL | автоповтор без реакции, NULL — не повторять |
| max_repeats | SMALLINT NOT NULL DEFAULT 2 | |
| planned_until | TIMESTAMPTZ NULL | докуда planner уже материализовал |
| created_at / updated_at | TIMESTAMPTZ NOT NULL DEFAULT now() | |

Индексы: `INDEX (status, planned_until) WHERE status = 'active'`; `INDEX (owner_id, status)`.

CHECK: `ends_at IS NULL OR ends_at > starts_at`; `schedule_kind::text = schedule->>'kind'`.

**reminder_recipients**

| поле | тип |
|---|---|
| id | BIGSERIAL PK |
| reminder_id | BIGINT NOT NULL FK reminders(id) ON DELETE CASCADE |
| user_id | BIGINT NOT NULL FK users(id) ON DELETE CASCADE |
| role | recipient_role NOT NULL |
| accepted_at | TIMESTAMPTZ NULL |
| created_at | TIMESTAMPTZ NOT NULL DEFAULT now() |

`UNIQUE (reminder_id, user_id)`. У каждого напоминания ровно одна строка с `role = 'owner'` (обеспечивается сервисом + partial unique index).

**occurrences** — одно плановое срабатывание. Это и есть очередь.

| поле | тип | описание |
|---|---|---|
| id | BIGSERIAL PK | |
| reminder_id | BIGINT NOT NULL FK reminders(id) ON DELETE CASCADE | |
| scheduled_for | TIMESTAMPTZ NOT NULL | плановый момент, UTC |
| fire_at | TIMESTAMPTZ NOT NULL | `scheduled_for` после сдвига тихими часами |
| status | occurrence_status NOT NULL DEFAULT 'pending' | |
| repeats_sent | SMALLINT NOT NULL DEFAULT 0 | |
| expires_at | TIMESTAMPTZ NOT NULL | после — `expired`, реакции не принимаются |
| created_at / updated_at | TIMESTAMPTZ NOT NULL DEFAULT now() | |

`UNIQUE (reminder_id, scheduled_for)` — ключ идемпотентности планировщика.
`INDEX (fire_at) WHERE status = 'pending'`.

**deliveries** — доставка одного occurrence одному получателю.

| поле | тип | описание |
|---|---|---|
| id | BIGSERIAL PK | |
| occurrence_id | BIGINT NOT NULL FK occurrences(id) ON DELETE CASCADE | |
| user_id | BIGINT NOT NULL FK users(id) ON DELETE CASCADE | |
| status | delivery_status NOT NULL DEFAULT 'pending' | |
| attempts | SMALLINT NOT NULL DEFAULT 0 | |
| next_attempt_at | TIMESTAMPTZ NOT NULL | |
| locked_until | TIMESTAMPTZ NULL | аренда воркера |
| tg_message_id | BIGINT NULL | для редактирования после реакции |
| sent_at | TIMESTAMPTZ NULL | |
| reacted_at | TIMESTAMPTZ NULL | |
| snoozed_until | TIMESTAMPTZ NULL | |
| error_code | TEXT NULL | |
| created_at / updated_at | TIMESTAMPTZ NOT NULL DEFAULT now() | |

`UNIQUE (occurrence_id, user_id)` — ключ идемпотентности доставки.
`INDEX (next_attempt_at) WHERE status IN ('pending', 'snoozed')`.

**delivery_actions** — журнал реакций, источник статистики.

| поле | тип |
|---|---|
| id | BIGSERIAL PK |
| delivery_id | BIGINT NOT NULL FK deliveries(id) ON DELETE CASCADE |
| user_id | BIGINT NOT NULL FK users(id) ON DELETE CASCADE |
| kind | action_kind NOT NULL |
| payload | JSONB NOT NULL DEFAULT '{}' |
| created_at | TIMESTAMPTZ NOT NULL DEFAULT now() |

`UNIQUE (delivery_id, kind, created_at)` не ставим; вместо этого сервис `reactions` отклоняет вторую терминальную реакцию по статусу delivery. Журнал append-only, строки не удаляются и не обновляются.

**fsm_states** — хранилище FSM aiogram, чтобы мастер создания переживал рестарт.

| поле | тип |
|---|---|
| key | TEXT PK |
| state | TEXT NULL |
| data | JSONB NOT NULL DEFAULT '{}' |
| updated_at | TIMESTAMPTZ NOT NULL DEFAULT now() |

Записи старше 24 часов чистит `reaper`.

---

## 5. Контракт расписаний (`reminders.schedule`, JSONB)

Discriminated union по полю `kind`. Модели живут в `app/domain/schedules.py`, валидируются Pydantic v2. Все времена — **локальное настенное время** в `reminders.timezone`, формат `HH:MM`, 24 часа. Дни недели — 1..7, понедельник = 1 (ISO). Список времён всегда отсортирован и без дублей (валидатор нормализует).

```jsonc
// разовое
{"kind": "once", "at": "2026-09-01T07:30"}

// интервальное, с окном активности
{"kind": "interval", "every_minutes": 120, "window_start": "09:00", "window_end": "21:00"}

// ежедневное, через N дней
{"kind": "daily", "times": ["08:00", "20:00"], "every_n_days": 1}

// по дням недели
{"kind": "weekly", "times": ["07:30"], "weekdays": [1, 3, 5]}

// по числам месяца
{"kind": "monthly", "times": ["10:00"], "days": [1, 15], "on_missing_day": "last_day"}
```

Ограничения:
- `every_minutes` ∈ [5, 1440];
- `times` — 1..12 элементов;
- `weekdays` — 1..7 элементов из 1..7;
- `days` — 1..31, значения 1..31; `on_missing_day` ∈ `last_day | skip`;
- окно `window_start`/`window_end` может пересекать полночь (`22:00`–`02:00`).

### 5.1 Правила времени (обязательны к соблюдению в `recurrence.py`)

1. Для `daily`, `weekly`, `monthly`, `once` при переходе на летнее/зимнее время выигрывает **настенное время**: 07:30 остаётся 07:30.
2. Для `interval` выигрывает **абсолютный интервал**: расстояние между срабатываниями всегда `every_minutes` независимо от переводов часов.
3. Несуществующее локальное время (весенний перевод) сдвигается вперёд к первому существующему моменту.
4. Неоднозначное локальное время (осенний перевод) берётся по первому (раннему) смещению.
5. Результат всегда timezone-aware UTC, строго возрастающий, без дублей.

### 5.2 API доменной функции

```python
def next_occurrences(
    schedule: Schedule,
    tz: ZoneInfo,
    after: datetime,      # UTC-aware, исключительно
    until: datetime,      # UTC-aware, включительно
    limit: int,
) -> list[datetime]:      # UTC-aware, отсортирован по возрастанию
```

Функция чистая: не читает часы, не ходит в БД, не логирует.

---

## 6. Контракт callback-данных

aiogram `CallbackData`, лимит Telegram — 64 байта на `callback_data`. Префиксы короткие и зафиксированы навсегда.

```python
class ReactCb(CallbackData, prefix="r"):
    delivery_id: int
    action: Literal["done", "snooze", "skip"]

class RemCb(CallbackData, prefix="m"):
    reminder_id: int
    action: Literal["open", "pause", "resume", "edit", "delete", "confirm_delete"]

class CatCb(CallbackData, prefix="c"):
    category_id: int
    action: Literal["pick", "open", "rename", "archive"]

class PageCb(CallbackData, prefix="p"):
    scope: Literal["rem", "cat", "today"]
    page: int

class WizCb(CallbackData, prefix="w"):
    step: str      # <= 12 символов
    value: str     # <= 24 символа
```

Правила:
- новый экран — новая фабрика, а не перегрузка `value` строкой с разделителями;
- контрактный тест на каждую фабрику: round-trip `pack -> unpack` и длина `pack()` ≤ 64 байта при максимальных значениях полей;
- `delivery_id`, а не `occurrence_id`, в кнопке реакции: реакцию всегда совершает конкретный получатель.

---

## 7. Контракты воркеров

Внешнего брокера нет, но джобы описаны как контракты и тестируются как джобы. Каждый цикл воркера — отдельная функция с явным `now: datetime` из `Clock`.

### 7.1 `planner.materialize`

- Период: каждые 60 секунд.
- Вход: активные напоминания с `planned_until IS NULL OR planned_until < now + horizon`.
- Горизонт: `PLANNER_HORIZON_HOURS` (по умолчанию 48).
- Действие: `next_occurrences(...)` → вставка occurrences пачкой `INSERT ... ON CONFLICT (reminder_id, scheduled_for) DO NOTHING`, затем `fire_at = apply_quiet_hours(...)`, затем создание `deliveries` на всех получателей с `accepted_at IS NOT NULL` (владелец считается принявшим всегда), затем обновление `planned_until` и `fired_count`.
- Идемпотентность: unique-ключ `(reminder_id, scheduled_for)` + `(occurrence_id, user_id)`. Повторный прогон на том же входе не создаёт ни одной новой строки.
- Границы: если `fired_count >= max_occurrences` или `scheduled_for > ends_at` — материализация прекращается, напоминание переводится в `archived`.
- Ретраи: цикл падает целиком → следующий тик повторит. Частичный успех допустим, состояние остаётся консистентным.

### 7.2 `dispatcher.deliver`

- Период: каждые `DISPATCH_INTERVAL_SECONDS` (по умолчанию 10).
- Claim: `UPDATE deliveries SET locked_until = now + 60s, attempts = attempts + 1 WHERE id IN (SELECT id FROM deliveries WHERE status IN ('pending','snoozed') AND next_attempt_at <= now AND (locked_until IS NULL OR locked_until < now) ORDER BY next_attempt_at LIMIT :batch FOR UPDATE SKIP LOCKED) RETURNING *`.
- Действие: `BotGateway.send_reminder(...)` → `status = 'sent'`, `sent_at`, `tg_message_id`, occurrence → `sent`.
- Гарантия: **at-least-once**. Падение между отправкой и коммитом даёт повторное сообщение после истечения `locked_until`. Продуктовое следствие допустимо; реакция на дубль идемпотентна, статистика не двоится, потому что терминальный переход `deliveries.status` выполняется один раз.
- Ретраи и ошибки:

| ситуация | реакция |
|---|---|
| `TelegramRetryAfter(retry_after=N)` | `next_attempt_at = now + N + 1s`, `attempts` не считается фатальным |
| `TelegramForbiddenError` (бот заблокирован) | `delivery.status = 'blocked'`, `user.is_blocked = true`, ретраев нет |
| `TelegramBadRequest` (невалидный payload) | `status = 'failed'`, `error_code`, ретраев нет, лог уровня error |
| сеть, 5xx, таймаут | backoff `min(30s * 2^(attempts-1), 30min)`, до `attempts = 5`, дальше `failed` |

- Backoff считает чистая функция `domain/retry.py: next_attempt(attempts, error_class, now) -> datetime`.

### 7.3 `reaper.sweep`

- Период: каждые 60 секунд.
- Просрочка: `deliveries.status = 'sent'` и `occurrence.expires_at < now` → `delivery_actions(kind='auto_expire')`, `occurrence.status = 'expired'`, сообщение редактируется (кнопки снимаются).
- Автоповтор: `sent`, реакции нет, `repeat_after_minutes` задан, `repeats_sent < max_repeats` → `status = 'pending'`, `next_attempt_at = now`, `repeats_sent += 1`.
- Чистка `fsm_states` старше 24 часов.
- Разблокировка зависших: `locked_until < now` и `status = 'pending'` → снять аренду.

### 7.4 Реакции пользователя (`services/reactions.py`)

| действие | эффект |
|---|---|
| `done` | `delivery.status = 'done'`, `reacted_at`, action-запись; если все deliveries occurrence терминальны — `occurrence.status = 'done'` |
| `skip` | `delivery.status = 'skipped'`, action-запись |
| `snooze` | `delivery.status = 'snoozed'`, `snoozed_until = now + reminder.snooze_minutes`, `next_attempt_at = snoozed_until`, action-запись |

Идемпотентность: реакция на delivery, уже находящуюся в терминальном статусе (`done`, `skipped`, `expired`), не меняет состояние и не пишет action; пользователь получает ответ-подтверждение через `answer_callback_query`. Обработка идёт под `SELECT ... FOR UPDATE` на строке delivery.

---

## 8. Протоколы и фейки

Всё внешнее — за протоколом. Разработка идёт против фейка с первого дня, реальный токен для локального запуска не нужен.

```python
# app/core/clock.py
class Clock(Protocol):
    def now(self) -> datetime: ...        # timezone-aware UTC

# app/gateways/bot_gateway.py
@dataclass(frozen=True)
class OutgoingMessage:
    chat_id: int
    text: str
    keyboard: InlineKeyboardMarkup | None
    parse_mode: str = "HTML"

@dataclass(frozen=True)
class MessageRef:
    chat_id: int
    message_id: int

class BotGateway(Protocol):
    async def send(self, message: OutgoingMessage) -> MessageRef: ...
    async def edit(self, ref: MessageRef, text: str, keyboard: InlineKeyboardMarkup | None) -> None: ...
```

`FakeBotGateway` (в `app/gateways/fakes.py`, не в тестах — используется и dev-режимом):
- пишет вызовы в список `sent: list[OutgoingMessage]`;
- **валидирует контракт**: `chat_id != 0`, `len(text) <= 4096`, все `callback_data` кнопок распаковываются известной фабрикой и укладываются в 64 байта. Нарушение — `ContractViolation`, тест падает;
- программируется на ошибку: `fake.fail_next(TelegramRetryAfter(retry_after=5))`.

`FakeClock` — `now()` возвращает заданный момент, `advance(timedelta)` двигает его. Прямой вызов `datetime.now()` / `datetime.utcnow()` вне `SystemClock` запрещён и ловится линт-правилом ruff (`flake8-datetimez`, `DTZ`).

---

## 9. Общие UI-примитивы

Тимлид собирает заранее, разработчик использует и не пишет свои клавиатуры с нуля.

| примитив | файл | контракт |
|---|---|---|
| `reminder_actions_kb(delivery_id, snooze_minutes)` | `bot/keyboards/actions.py` | три кнопки: Готово / Отложить N мин / Пропустить |
| `paginated_kb(items, scope, page, page_size=8)` | `bot/keyboards/pagination.py` | сетка 1 колонка + строка навигации, скрывает стрелки на краях |
| `category_picker_kb(categories, page)` | `bot/keyboards/pickers.py` | сетка 2×4 + «Новая категория» |
| `time_picker_kb(step)` | `bot/keyboards/pickers.py` | быстрые пресеты + «Ввести вручную» |
| `weekday_picker_kb(selected)` | `bot/keyboards/pickers.py` | тумблеры Пн..Вс + «Готово» |
| `confirm_kb(action, entity_id)` | `bot/keyboards/confirm.py` | Да / Отмена |
| `render_reminder_card(reminder, category, next_fire)` | `bot/render/reminder.py` | HTML-текст карточки |
| `render_reminder_list(items, page, total)` | `bot/render/lists.py` | нумерованный список с ближайшим временем |
| `render_stats(summary)` | `bot/render/stats.py` | streak, доля выполненных за 7/30 дней |
| `T(key, lang, **kwargs)` | `bot/render/texts.py` | все строки только отсюда, литералов в хендлерах нет |

Все клавиатуры возвращают `InlineKeyboardMarkup` и собираются через `InlineKeyboardBuilder`. Reply-клавиатуру используем только для главного меню.

---

## 10. Стратегия тестов

Тесты привязаны к слайсу и PR, не к стадии. Слайс мёржится только с тестами, гейт красный без них.

Главное правило: **тесты выводятся из критериев приёмки задачи, а не из реализации**. Тест кодирует контракт, не зеркалит код. Запрещено писать тест, который повторяет ветвления функции и фиксирует её текущее поведение вместе с багами.

Обязательные типы тестов на слайс:

1. **Контрактные на стыках.** Payload расписания валиден против модели из `domain/schedules.py`. Исходящее сообщение проходит валидацию `FakeBotGateway`. `CallbackData` укладывается в 64 байта и переживает round-trip. Фейк — это и есть тестовый шов: он падает, когда слайс шлёт мусор.
2. **Идемпотентность.** На каждый цикл воркера и на каждую реакцию — тест, который прогоняет операцию дважды с тем же входом и проверяет, что эффект ровно один: одна строка occurrence, одно сообщение, одна action-запись. Без такого теста PR не проходит ревью.
3. **Путь ошибки.** Гейтвей вернул `TelegramRetryAfter`, `TelegramForbiddenError`, таймаут. Проверяется, что статус, `attempts` и `next_attempt_at` меняются по таблице §7.2, а сообщение не теряется.
4. **Property-based (Hypothesis) на чистой доменной логике.** Обязательно для `recurrence.py`, `quiet_hours.py`, `retry.py`, `stats.py`.

Инварианты `next_occurrences`, проверяемые Hypothesis:
- результат строго возрастает и не содержит дублей;
- все элементы в полуинтервале `(after, until]`;
- все элементы timezone-aware и в UTC;
- `len(result) <= limit`;
- при `ends_at` в расписании ни один элемент его не превышает;
- для `daily`/`weekly`/`monthly` локальное время каждого элемента входит в `times` (проверка правила «настенное время выигрывает» через DST-границы `Europe/Moscow` не сработает — используй `Europe/Berlin`, `America/New_York`, `Australia/Lord_Howe` с получасовым сдвигом);
- для `interval` разница между соседними элементами внутри одного окна ровно `every_minutes`;
- детерминизм: два вызова с теми же аргументами дают тот же список;
- склейка: `next_occurrences(after=a, until=c)` равен конкатенации вызовов по `(a, b]` и `(b, c]`.

Стратегии Hypothesis для дат объявляй один раз в `tests/unit/strategies.py` и переиспользуй.

### 10.1 Организация

- `tests/unit/` — только `app/domain`. Без БД, без event loop там, где не нужен. Быстрые.
- `tests/contract/` — схемы, CallbackData, фейки. Без БД.
- `tests/integration/` — реальный Postgres. Схема поднимается один раз через `alembic upgrade head`, каждый тест в откатываемой транзакции (`SAVEPOINT`), фикстура `db_session`.
- `tests/e2e/` — сценарий целиком: апдейт → хендлер → сервис → БД → planner → dispatcher → `FakeBotGateway` → реакция.

Фикстуры в `tests/conftest.py`: `db_session`, `fake_clock`, `fake_bot`, `user_factory`, `reminder_factory`, `freeze_at`.

Правило: если тест нуждается в `sleep`, он написан неправильно — двигай `FakeClock`.

Покрытие: гейт требует ≥ 85% по `app/domain` и `app/services`, остальное без порога.

---

## 11. Конфигурация и владение инфраструктурой

### 11.1 `.env.example`

```
ENV=dev                          # dev | test | prod
LOG_LEVEL=INFO
BOT_TOKEN=000000:fake-token-for-local-dev
BOT_MODE=polling                 # polling | webhook
WEBHOOK_BASE_URL=
DATABASE_URL=postgresql+asyncpg://app:app@db:5432/reminder
DEFAULT_TIMEZONE=Europe/Moscow
DEFAULT_LANGUAGE=ru
PLANNER_HORIZON_HOURS=48
PLANNER_INTERVAL_SECONDS=60
DISPATCH_INTERVAL_SECONDS=10
DISPATCH_BATCH_SIZE=100
DELIVERY_LOCK_SECONDS=60
OCCURRENCE_TTL_MINUTES=180
USE_FAKE_BOT=false               # true — dev без реального токена
ADMIN_USER_IDS=
```

Окружение читается ровно в одном месте — `app/core/config.py`. `os.environ` в остальном коде запрещён.

### 11.2 Владение (только тимлид)

- **Миграции Alembic.** Разработчик миграции не пишет вообще. Изменил модель — оформляет `CONTRACT GAP`. Миграции применяются в деплой-шаге и прогоняются на эфемерном Postgres в PR-гейте. Ревизии линейные, ветвление запрещено.
- **Схема БД** (`app/db/models/`), **контракты** (`app/domain/contracts.py`, `app/domain/schedules.py`), **CallbackData** (`app/bot/callbacks.py`), **клавиатуры-примитивы** (`app/bot/keyboards/`), **тексты** (`app/bot/render/texts.py`), **конфиг**, **seed**, **CI**.
- **Seed-скрипт** `scripts/seed.py` — общие фикстуры для всей команды и фейков: 6 системных категорий, демо-пользователь, 3 демо-напоминания разных `schedule_kind`.

---

## 12. Правила кода

- Python 3.12, `from __future__ import annotations` не нужен.
- Типы обязательны на всех публичных функциях. mypy strict на `app/domain` и `app/services`, обычный режим на остальном.
- Асинхронность сквозная. Синхронный IO в async-функции запрещён.
- Никаких `datetime.now()`, `datetime.utcnow()`, `date.today()` вне `SystemClock`. Все datetime timezone-aware.
- Никакой бизнес-логики в хендлерах aiogram и в репозиториях.
- `domain/` не импортирует ничего из `db/`, `bot/`, `gateways/`, `services/`.
- Транзакции открывает только `services/`. Репозиторий получает сессию, но не коммитит.
- Исключения: доменные из `domain/errors.py`, наружу пользователю — через `bot/handlers/errors.py`, пользователю никогда не показывается трейсбек.
- Логи структурные, с `user_id`, `reminder_id`, `delivery_id`. Токен бота и содержимое сообщений в логи не попадают.
- Имена: таблицы во множественном числе, поля `snake_case`, время всегда с суффиксом (`_at` для момента, `_minutes`/`_seconds` для длительности).
- Строки пользователю — только через `T(...)`.
- Длина строки 100, форматирование ruff, импорты отсортированы.

### 12.1 Конвенция коммитов, PR и комментариев

- Язык всего кода, коммитов, PR и комментариев — только английский. Документация в репозитории может быть на русском.
- Формат коммита фиксированный, всегда Conventional Commits: `type(scope): summary`. `type` из закрытого набора `feat|fix|test|refactor|chore|docs`. `scope` — имя слайса или модуля (`planner`, `reminders`, `db`). `summary` в императиве, со строчной буквы, без точки, до ~50 символов. Тело только если нужно объяснить *почему*.
- Сессия коммитит сама по ходу работы, маленькими логическими коммитами после каждого осмысленного шага, не сваливает всё одним коммитом в конце. Каждый коммит по возможности проходит тайпчек.
- PR: заголовок краткий, содержит ID задачи. Тело короткое: что делает слайс, какие контракты и типы затрагивает, чем покрыт тестами.
- Комментарии в коде кратко и по делу, объясняют *почему*, а не пересказывают очевидный код. Закомментированный код в PR не оставлять.
- Проза активным залогом, без филлеров, без em-dash, без маркетинга.

Примеры: `feat(planner): materialize occurrences within horizon`, `fix(dispatcher): keep retry-after delay out of backoff`, `test(recurrence): add dst invariants for weekly schedules`.

### 12.2 Авторство коммитов и PR

Все коммиты и PR идут от владельца репозитория. Настроить локально до первого коммита:

```bash
git config user.name "AZAZ3LL0"
git config user.email "sadrievsamat4@gmail.com"
git remote add origin git@github.com:AZAZ3LL0/<repo>.git
```

Правила:

- автор и коммиттер каждого коммита — `AZAZ3LL0 <sadrievsamat4@gmail.com>`. Перед пушем сверяйся: `git log --format='%an <%ae> | %cn <%ce>' -5`;
- трейлеры `Co-authored-by`, `Signed-off-by`, упоминания инструментов и генерации в теле коммита, в описании PR и в комментариях к ревью запрещены. Тело коммита содержит только причину изменения;
- PR создаётся из ветки задачи в `main`: `gh pr create --title "<ID> <summary>" --body-file .github/pr_body.md`. Заголовок и тело на английском;
- `--author` и правка авторства через `--amend` для чужих коммитов не применяются: история линейная и однопользовательская;
- если email коммита не совпадает с привязанным к GitHub-аккаунту, коммит теряет привязку к профилю. Проверяется на первом же PR по аватару в списке коммитов.

---

## 13. Definition of Done одной задачи

1. `make lint` зелёный (ruff check + ruff format --check).
2. `make typecheck` зелёный.
3. `make test` зелёный локально и в CI.
4. Миграции применяются на чистой БД и на БД предыдущей ревизии.
5. Тесты выведены из критериев приёмки задачи, не из реализации.
6. Для каждого цикла воркера и каждой реакции есть тест идемпотентности.
7. На стыке слайса есть контрактный тест.
8. Есть тест пути ошибки, если слайс ходит в Telegram.
9. Для чистой доменной логики есть property-based тест.
10. Общие файлы (§11.2) не изменены без апрува тимлида.
11. Новых строк пользователю вне `texts.py` нет.
12. PR привязан к задаче, коммиты по конвенции.

---

## 14. Чек-лист «скелет готов»

Разработка фич не начинается, пока все пункты не зелёные:

- [ ] CI зелёный на тривиальном PR;
- [ ] `docker compose up` поднимает `db`, `bot`, `worker` из чистого клона при `USE_FAKE_BOT=true` и без реального токена;
- [ ] Alembic-миграции проходят на эфемерном Postgres в PR-гейте;
- [ ] `/start` отвечает, пользователь создаётся, таймзона спрашивается;
- [ ] FSM-состояние переживает рестарт процесса `bot`;
- [ ] `scripts/seed.py` создаёт 6 системных категорий, демо-пользователя и 3 напоминания;
- [ ] planner материализует occurrence для демо-напоминания;
- [ ] dispatcher доставляет его через `FakeBotGateway`, кнопки распаковываются;
- [ ] реакция `done` меняет статус и пишет `delivery_actions`;
- [ ] эталонный слайс «Вода» в `main` с полным набором из четырёх типов тестов;
- [ ] задеплоено на тестовый VPS автодеплоем из `main`.

---

## 15. Дорожная карта

Каждая задача = один вертикальный слайс = один PR.

**S0. Скелет (тимлид).** Репозиторий, Docker, compose, Alembic, модели всех таблиц, enum-ы, контракты, конфиг, Clock, BotGateway + фейк, FSM-хранилище, клавиатуры-примитивы, тексты, seed, CI-гейт, деплой, эталонный слайс «Вода».

**S1. Онбординг и настройки.** `/start`, создание пользователя, выбор таймзоны (популярные + ручной ввод IANA), язык, тихие часы, `/settings`.

**S2. Категории.** Список системных и своих, создание с эмодзи, переименование, архивация. Запрет удаления категории с активными напоминаниями.

**S3. Создание напоминания: разовое и ежедневное.** Мастер FSM: категория → название → тип расписания → время → подтверждение. Карточка после создания.

**S4. Planner.** Материализация occurrences на горизонт, `planned_until`, границы `ends_at` и `max_occurrences`, архивация исчерпанных.

**S5. Dispatcher.** Claim через `SKIP LOCKED`, отправка, статусы, backoff, обработка `RetryAfter` и блокировки бота.

**S6. Реакции.** Кнопки Готово / Отложить / Пропустить, редактирование сообщения после реакции, идемпотентность повторного нажатия.

**S7. Остальные расписания.** `interval` с окном, `weekly`, `monthly` с `on_missing_day`. Полный набор DST-инвариантов.

**S8. Тихие часы и автоповтор.** `apply_quiet_hours`, `repeat_after_minutes`, `reaper.sweep`, просрочка occurrence.

**S9. Управление напоминаниями.** `/list` с пагинацией и фильтром по категории, карточка, пауза/возобновление, редактирование, удаление с подтверждением, `/today`.

**S10. Совместные напоминания.** Приглашение другого пользователя по deep-link `t.me/<bot>?start=inv_<token>`, принятие, роль `watcher`, отписка, доставка всем принявшим.

**S11. Статистика.** Streak по категории, доля выполненных за 7 и 30 дней, `/stats`, недельный дайджест.

**S12. Ops.** Healthcheck-эндпоинт воркера, метрики (размер очереди, лаг доставки, доля ошибок), алерт при лаге > 5 минут, бэкап БД, ротация логов.

Long-lead: нет. Внешних согласований проект не требует, токен бота выдаёт BotFather мгновенно.

---

## 16. Контракт слайса S1 (онбординг и настройки)

Добавлено в `v3`. Раздел append-only, как и весь файл: значения ниже не переименовываются.

### 16.1 Язык и таймзоны (`domain/contracts.py`)

```python
class Language(StrEnum):
    RU = "ru"
    EN = "en"
```

`Language` хранится в `users.language` как TEXT, native enum в Postgres для него не заводится. Расширение — append-only, как у остальных enum §4.1.

```python
POPULAR_TIMEZONES: Final[tuple[str, ...]]
```

Восемь IANA-зон, предлагаемых кнопками на онбординге. Список намеренно короткий и не полный: всё остальное пользователь вводит вручную IANA-именем. Инварианты, закреплённые контрактным тестом:

- каждое имя резолвится `zoneinfo.ZoneInfo`;
- каждое имя укладывается в `SetCb` и в лимит 64 байта;
- ни одно имя не совпадает с зарезервированными значениями §16.3.

### 16.2 Формат настенного времени (`domain/schedules.py`)

`parse_hhmm(value) -> time` и `format_hhmm(value) -> str` становятся публичными. Формат `HH:MM`, 24 часа — один контракт на весь продукт: расписания §5, тихие часы, ручной ввод пользователя. Второй разбор `HH:MM` где-либо ещё запрещён.

### 16.3 CallbackData экрана настроек (`bot/callbacks.py`)

```python
class SetCb(CallbackData, prefix="s"):
    field: Literal["menu", "tz", "lang", "quiet"]
    value: str      # <= 32 символа
```

Префикс `s` заморожен наравне с §6. Семантика полей:

| `field` | допустимые `value` | эффект |
|---|---|---|
| `menu` | `root` \| `tz` \| `lang` \| `quiet` | открыть экран, состояние не меняется |
| `tz` | IANA-имя \| `manual` | сохранить таймзону либо уйти в ручной ввод |
| `lang` | `ru` \| `en` | сохранить язык |
| `quiet` | `edit` \| `off` | начать выбор интервала либо выключить тишину |

`value` несёт ровно один атом. Упаковка пары значений разделителем запрещена §6; двухшаговый выбор тихих часов идёт через состояние FSM, а не через составной `value`.

Зарезервированные значения: `root`, `manual`, `edit`, `off`.

Времена тихих часов выбираются существующей фабрикой `WizCb` со `step = "qs"` (начало) и `step = "qe"` (конец). `value` — настенное время атомом `HHMM` либо `man` для ручного ввода.

Двоеточие — разделитель CallbackData в aiogram и внутри `value` запрещено. Настенное время едет атомом без двоеточия через пару в `bot/callbacks.py`:

```python
def pack_wall_time(value: str) -> str      # "23:00" -> "2300"
def unpack_wall_time(value: str) -> str    # "2300" -> "23:00"
```

Это единственный допустимый способ положить время в `callback_data`; собирать строку вручную запрещено.

### 16.4 Клавиатуры (`bot/keyboards/settings.py`)

| примитив | контракт |
|---|---|
| `settings_kb(lang)` | корневой экран: Таймзона / Язык / Тихие часы |
| `timezone_picker_kb(lang, *, with_back)` | `POPULAR_TIMEZONES` + «Ввести вручную»; онбординг скрывает «Назад» |
| `language_picker_kb(current, lang)` | ru / en, текущий помечен |
| `quiet_menu_kb(lang, *, is_on)` | Задать / Выключить (только когда тишина включена) / Назад |
| `quiet_time_picker_kb(step, lang)` | часы 21:00–01:00 и 05:00–09:00 + ручной ввод |

`quiet_time_picker_kb` существует отдельно от `time_picker_kb` §9: пресеты последнего не содержат 23:00, самого частого начала тишины.

### 16.5 Ключи текстов (`bot/render/texts.py`)

`start.welcome_back`, `start.timezone_manual`, `settings.quiet_value`, `settings.pick_timezone`, `settings.pick_language`, `settings.pick_quiet`, `settings.pick_quiet_start`, `settings.pick_quiet_end`, `settings.time_manual`, `settings.quiet_saved`, `settings.quiet_cleared`, `settings.quiet_equal`, `settings.language_saved`, `settings.time_invalid`, `settings.saved`, `lang.ru`, `lang.en`, `btn.back`, `btn.timezone`, `btn.language`, `btn.quiet`, `btn.quiet_set`, `btn.quiet_off`.

У каждого ключа обязательны обе локали и совпадающий набор плейсхолдеров — держится контрактным тестом.

### 16.6 Модули слайса

Раскладка §3.1 дополняется тремя файлами, которые пишет слайс S1:

```
app/domain/onboarding.py     # чистая валидация языка, таймзоны и тихих часов
app/bot/fsm/onboarding.py    # состояния Onboarding и SettingsForm
app/bot/render/settings.py   # рендер экрана настроек
```

Публичный API домена:

```python
def normalize_language(raw: str) -> Language
def normalize_timezone(raw: str) -> str
def parse_wall_time(raw: str) -> time
def normalize_quiet_hours(start: time | None, end: time | None) -> tuple[time, time] | None
```

Правила тихих часов, обязательные к соблюдению:

1. `quiet_start` и `quiet_end` задаются и снимаются только вместе (CHECK §4.2);
2. равные начало и конец отвергаются: `is_quiet` §8 на таком интервале всегда ложна, то есть настройка молча не работала бы;
3. интервал через полночь допустим, `quiet_start > quiet_end` — нормальное состояние;
4. функции чистые: ни часов, ни IO, ни импортов вне stdlib.

---

## 17. Контракт слайса S2 (категории)

Добавлено в `v4`. Раздел append-only, как и весь файл: значения ниже не переименовываются.

### 17.1 CallbackData экрана категорий (`bot/callbacks.py`)

`CatCb` из §6 расширяется одним действием. Префикс `c` заморожен, набор действий append-only:

```python
class CatCb(CallbackData, prefix="c"):
    category_id: int
    action: Literal["pick", "open", "rename", "archive", "confirm_archive"]
```

| `action` | эффект |
|---|---|
| `pick` | выбрать категорию в мастере напоминания |
| `open` | открыть карточку категории |
| `rename` | начать ввод нового названия |
| `archive` | спросить подтверждение |
| `confirm_archive` | архивировать |

Архивация подтверждается, потому что она прячет категорию из всех пикеров. Разрушающего удаления у категорий нет вообще: строка нужна напоминаниям в архиве, а FK `reminders.category_id` стоит на `ON DELETE RESTRICT` §4.2.

Создание категории и выбор эмодзи идут существующей фабрикой `WizCb`, отдельной фабрики на это не заводится:

| `step` | `value` | эффект |
|---|---|---|
| `cat` | `new` | начать создание категории |
| `cat` | `cancel` | выйти из создания или переименования |
| `emoji` | эмодзи атомом \| `man` | взять эмодзи с кнопки либо уйти в ручной ввод |

Зарезервированные значения: `new`, `cancel` для шага `cat`, `man` для шага `emoji`. Ни одно эмодзи-пресет с ними не совпадает, это держит контрактный тест. Возврат к списку — `PageCb(scope="cat", page=0)`, новая фабрика для навигации не нужна.

### 17.2 Ограничения категории (`domain/contracts.py`)

```python
CATEGORY_TITLE_MAX_LENGTH: Final = 64
CATEGORY_CODE_PATTERN: Final = r"^[a-z0-9_]{2,32}$"
DEFAULT_CATEGORY_EMOJI: Final = "\U0001f514"
```

`CATEGORY_CODE_PATTERN` дублирует CHECK `code_is_slug` §4.2, `DEFAULT_CATEGORY_EMOJI` — `server_default` колонки. Оба продублированы намеренно: домен обязан отвергать значение раньше, чем его отвергнет БД.

Код категории пользователь не вводит. Код выводится из названия чистой функцией слайса §17.6 и обязан удовлетворять паттерну при любом названии, включая кириллицу, иероглифы и строку из одних эмодзи. Коллизия внутри владельца разрешается числовым суффиксом, лимит длины при этом не нарушается.

### 17.3 Эмодзи категории

`categories.emoji` — ровно один графемный кластер §4.2. Проверка чистая и без внешних зависимостей: кластером считается базовый символ вместе с идущими за ним модификаторами.

1. вариационные селекторы `U+FE0E`, `U+FE0F`;
2. модификаторы тона кожи `U+1F3FB..U+1F3FF`;
3. комбинирующие знаки категорий `Mn` и `Me`;
4. keycap `U+20E3`;
5. последовательности, склеенные `ZWJ` `U+200D`;
6. пара региональных индикаторов `U+1F1E6..U+1F1FF` — один кластер (флаг).

Пробелы, переводы строк и управляющие символы запрещены. Пустая строка не эмодзи.

### 17.4 Клавиатуры (`bot/keyboards/categories.py`)

| примитив | контракт |
|---|---|
| `category_list_kb(categories, page, total_pages, lang)` | страница списка поверх `paginated_kb` §9 + «Новая категория» |
| `category_card_kb(category_id, lang, *, editable)` | Переименовать / В архив только у своих, Назад всегда |
| `emoji_picker_kb(lang)` | `EMOJI_PRESETS` + «Ввести вручную» + «Отмена» |

Размер страницы общий с пикером категорий §9: `CATEGORY_PAGE_SIZE`. Второй константы на это не заводится.

`confirm_kb(action, entity_id)` §9 принимает третье действие `archive`; кнопка «Да» шлёт `CatCb(action="confirm_archive")`, кнопка «Отмена» остаётся общей `WizCb(step="confirm", value="no")`.

### 17.5 Ключи текстов (`bot/render/texts.py`)

`categories.item`, `categories.card`, `categories.kind_system`, `categories.kind_own`, `categories.ask_title`, `categories.ask_emoji`, `categories.emoji_manual`, `categories.created`, `categories.ask_new_title`, `categories.renamed`, `categories.confirm_archive`, `categories.archived`, `categories.already_archived`, `categories.in_use`, `categories.system_readonly`, `categories.title_invalid`, `categories.emoji_invalid`, `categories.duplicate`, `categories.cancelled`, `btn.rename`, `btn.archive`.

`categories.title` и `categories.empty` уже есть с `v1` и не меняются. У каждого ключа обязательны обе локали и совпадающий набор плейсхолдеров — держится контрактным тестом.

### 17.6 Модули слайса

Раскладка §3.1 дополняется тремя файлами, которые пишет слайс S2:

```
app/domain/categories.py     # чистая валидация названия, эмодзи и вывод кода
app/bot/fsm/categories.py    # состояния CategoryForm
app/bot/render/categories.py # рендер списка и карточки категории
```

Публичный API домена:

```python
def normalize_category_title(raw: str) -> str
def normalize_emoji(raw: str) -> str
def slugify_code(title: str) -> str
def next_free_code(base: str, taken: Collection[str]) -> str
```

Правила, обязательные к соблюдению:

1. название нормализуется до сравнения: обрезка по краям и схлопывание внутренних пробелов, длина 1..`CATEGORY_TITLE_MAX_LENGTH`;
2. `slugify_code` детерминирована: одно и то же название всегда даёт один и тот же код, вызов часов и случайности запрещены;
3. `next_free_code` возвращает код, которого нет в `taken`, и не выходит за паттерн §17.2;
4. системная категория и категория чужого владельца доступны только на чтение: переименование и архивация отвечают `PermissionDeniedError`;
5. название своей активной категории уникально внутри владельца без учёта регистра; нарушение — `CategoryExistsError` из `domain/errors.py`;
6. архивация категории с неархивированными напоминаниями — `CategoryInUseError`. Повторная архивация уже архивной категории эффекта не даёт и ошибкой не считается;
7. функции чистые: ни часов, ни IO, ни импортов вне stdlib.

---

## 18. Контракт слайса S3 (создание напоминания: разовое и ежедневное)

Добавлено в `v5`. Раздел append-only, как и весь файл: значения ниже не переименовываются.

### 18.1 CallbackData мастера (`bot/callbacks.py`)

Мастер идёт существующей фабрикой `WizCb`, отдельной фабрики на него не заводится. Префикс `w` заморожен наравне с §6, набор шагов append-only:

| `step` | `value` | эффект |
|---|---|---|
| `kind` | `once` \| `daily` \| `interval` | выбрать тип расписания |
| `date` | `today` \| `tmrw` \| `YYYY-MM-DD` \| `man` | день разового напоминания |
| `at` | `HHMM` \| `man` | время разового напоминания |
| `time` | `HHMM` \| `man` | добавить время в ежедневное расписание |
| `times` | `ok` | закончить список времён |

Зарезервированные значения: `once`, `daily`, `interval` для шага `kind`; `today`, `tmrw`, `man` для шага `date`; `man` для шагов `at` и `time`; `ok` для шага `times`. Ни один пресет времени с ними не совпадает, это держит контрактный тест.

Разделение шагов повторяет §16.3: два разных вопроса — два разных `step`, а не один шаг с составным `value`. Поэтому время разового напоминания едет шагом `at`, а время ежедневного — шагом `time`, хотя формат атома у них один.

Настенное время кладётся в `value` только парой `pack_wall_time`/`unpack_wall_time` §16.3. Дата едет ISO-строкой `YYYY-MM-DD` без упаковки: двоеточия в ней нет, а значит нет и конфликта с разделителем CallbackData.

Отмена мастера на любом шаге — общий атом `WizCb(step="confirm", value="no")` §17.4. Отдельного атома отмены у мастера нет.

Шаг `kind` предлагает `interval` наравне с `once` и `daily`: интервальное расписание уже собрано эталонным слайсом «Вода» §3.2, и спрятать его за отсутствующей кнопкой значит сломать эталон. `weekly` и `monthly` добавляются в тот же шаг в S7.

### 18.2 Ограничения напоминания (`domain/contracts.py`)

```python
REMINDER_TITLE_MAX_LENGTH: Final = 120
REMINDER_NOTE_MAX_LENGTH: Final = 1000
WIZARD_MAX_DAYS_AHEAD: Final = 366
```

Первые две константы дублируют §4.2 по той же причине, что и §17.2: домен обязан отвергнуть значение раньше, чем его отвергнет БД. `WIZARD_MAX_DAYS_AHEAD` — горизонт, дальше которого мастер не принимает дату разового напоминания и не ищет первое срабатывание. Год с запасом на високосный: дата дальше него почти всегда опечатка, а поиск первого момента остаётся ограниченным.

### 18.3 Формат даты и длина списка времён (`domain/schedules.py`)

`parse_local_date(value) -> date` и `format_local_date(value) -> str` становятся публичными. Формат `YYYY-MM-DD` — один контракт на весь продукт: разовое расписание §5 и ручной ввод пользователя. Второй разбор даты где-либо ещё запрещён, как и второй разбор `HH:MM` по §16.2.

```python
TIMES_MAX_LENGTH: Final = 12
```

Ограничение §5 на `times` получает имя: мастер обязан отказать в тринадцатом времени тем же числом, каким его отвергает модель. Литерал `12` в валидаторе заменяется на эту константу.

### 18.4 Клавиатуры (`bot/keyboards/wizard.py`)

| примитив | контракт |
|---|---|
| `schedule_kind_kb(lang)` | по кнопке на тип из `WIZARD_SCHEDULE_KINDS` + «Отмена» |
| `date_picker_kb(lang)` | Сегодня / Завтра + ручной ввод + «Отмена» |
| `once_time_kb(lang)` | `time_picker_kb("at")` §9 + «Отмена» |
| `daily_times_kb(selected, lang)` | `DAILY_TIME_PRESETS` с отметкой выбранных + ручной ввод + «Готово» + «Отмена» |

`date_picker_kb` предлагает только «Сегодня» и «Завтра»: любая другая дата приходит ручным вводом. Клавиатура остаётся чистой функцией и не читает часы, а значит не может предложить «послезавтра», не получив дату снаружи.

`once_time_kb` собирается поверх `time_picker_kb` §9, а не вместо неё: пресеты у них общие, у мастера добавляется только отмена. Так же, как `category_list_kb` §17.4 собирается поверх `paginated_kb`.

`daily_times_kb` — единственная клавиатура-тумблер в мастере: повторное нажатие на выбранное время снимает его. Длина списка ограничена `TIMES_MAX_LENGTH` §18.3.

### 18.5 Ключи текстов (`bot/render/texts.py`)

`wizard.pick_kind`, `wizard.ask_date`, `wizard.ask_at`, `wizard.ask_times`, `wizard.times_none`, `wizard.times_empty`, `wizard.times_full`, `wizard.date_manual`, `wizard.date_invalid`, `wizard.time_manual`, `wizard.time_invalid`, `wizard.past_moment`, `wizard.confirm_once`, `wizard.confirm_daily`, `wizard.title_invalid`, `btn.kind_once`, `btn.kind_daily`, `btn.kind_interval`, `btn.today`, `btn.tomorrow`.

Два ключа из `v1` переименованы, потому что после S3 их прежние имена врут о содержимом:

- `wizard.confirm` → `wizard.confirm_interval`: подтверждений теперь три, и безымянное из них ничем не лучше остальных;
- `wizard.title_too_long` → `wizard.title_invalid`: название теперь нормализуется и отвергается ещё и пустым, как `categories.title_invalid` §17.5.

Переименование допустимо только здесь: ключ текста — внутренний идентификатор, он не лежит в БД и не едет в `callback_data`. Значения enum-ов §4.1 и префиксы CallbackData §6 по-прежнему не переименовываются никогда.

`wizard.pick_category`, `wizard.ask_title`, `wizard.ask_interval`, `wizard.ask_window`, `wizard.created` и `wizard.cancelled` есть с `v1` и не меняются. У каждого ключа обязательны обе локали и совпадающий набор плейсхолдеров — держится контрактным тестом.

### 18.6 Модули слайса

Раскладка §3.1 дополняется тремя файлами, два из которых пишет слайс S3, а клавиатуры §18.4 — тимлид:

```
app/domain/reminders.py      # чистая валидация черновика мастера
app/bot/render/wizard.py     # рендер подтверждения и списка выбранных времён
app/bot/keyboards/wizard.py  # клавиатуры мастера
```

`app/bot/fsm/reminder_wizard.py` из §3.1 дополняется состояниями `kind`, `date`, `at`, `times`.

Публичный API домена:

```python
def normalize_reminder_title(raw: str) -> str
def parse_user_date(raw: str, today: date, max_days_ahead: int = WIZARD_MAX_DAYS_AHEAD) -> date
def local_today(now: datetime, tz: ZoneInfo) -> date
def build_once_schedule(day: date, at: time) -> OnceSchedule
def build_daily_schedule(times: Sequence[time]) -> DailySchedule
def first_fire_at(schedule: Schedule, tz: ZoneInfo, starts_at: datetime) -> datetime | None
```

Правила, обязательные к соблюдению:

1. название нормализуется так же, как название категории §17.6: обрезка по краям и схлопывание внутренних пробелов, длина 1..`REMINDER_TITLE_MAX_LENGTH`;
2. `parse_user_date` принимает дату из отрезка `[today, today + max_days_ahead]`; вчерашняя дата и дата за горизонтом отвергаются одинаково — `ValidationError`;
3. `first_fire_at` считает границу так же, как planner §7.1: `after` полуоткрыт, поэтому момент ровно в `starts_at` не теряется. Расхождение с planner означало бы, что мастер и воркер видят разные первые срабатывания;
4. `first_fire_at` ищет не дальше `starts_at + WIZARD_MAX_DAYS_AHEAD` и возвращает `None`, когда впереди ничего нет;
5. создание напоминания без единого будущего срабатывания отвергается `ScheduleExhaustedError` из `domain/errors.py`. Разовое напоминание на прошедшую минуту — типичный случай: planner никогда не материализует его, и молча созданная строка выглядела бы работающей;
6. функции чистые: ни часов, ни IO, ни импортов вне stdlib и `app/domain`.

### 18.7 Границы слайса

Мастер создаёт напоминание со значениями по умолчанию из §4.2: `snooze_minutes = 10`, `repeat_after_minutes = NULL`, `ends_at = NULL`, `max_occurrences = NULL`, `note = NULL`. Экранов для них в S3 нет, редактирование приходит в S9.

`starts_at` — момент создания по `Clock`. Разовое расписание уже несёт свой момент, ежедневное начинает работать сразу.

---

## 19. Контракт слайса S7 (остальные расписания)

Добавлено в `v6`. Раздел append-only, как и весь файл: значения ниже не переименовываются.

### 19.1 CallbackData оставшихся шагов мастера (`bot/callbacks.py`)

Мастер по-прежнему идёт фабрикой `WizCb`, отдельной фабрики на новые расписания не заводится. Префикс `w` заморожен наравне с §6, набор шагов append-only и дополняет таблицу §18.1:

| `step` | `value` | эффект |
|---|---|---|
| `kind` | `weekly` \| `monthly` | выбрать тип расписания |
| `wday` | `1`..`7` \| `ok` | переключить день недели, закончить список |
| `mday` | `1`..`31` \| `ok` | переключить число месяца, закончить список |
| `miss` | `last` \| `skip` | что делать в месяце без нужного числа |
| `every` | `5`..`1440` \| `man` | шаг интервала |
| `window` | `HHMMHHMM` \| `man` | окно активности интервала |

Зарезервированные значения: `weekly`, `monthly` для шага `kind`; `ok` для шагов `wday` и `mday`; `last`, `skip` для шага `miss`; `man` для шагов `every` и `window`. Ни один пресет с ними не совпадает, это держит контрактный тест.

Дни недели считаются по ISO, понедельник = 1, как в §5. Значения `last` и `skip` шага `miss` отображаются на `on_missing_day` §5 один к одному: `last` в `last_day`, `skip` в `skip`. Атом шага короче поля модели, потому что 64 байта §6 делятся между префиксом, шагом и значением.

Окно едет одним атомом, хотя §6 запрещает паковать пару значений разделителем. Разделителя здесь нет, и главное: окно — **один ответ на один вопрос** («в какое окно дня напоминать»), его концы никогда не выбираются по отдельности. Тихие часы §16.3 — обратный случай: там два разных вопроса, и потому два разных `step`. Атом собирается только парой:

```python
def pack_window(start: str, end: str) -> str        # "09:00", "21:00" -> "09002100"
def unpack_window(value: str) -> tuple[str, str]    # "09002100" -> ("09:00", "21:00")
```

Это единственный допустимый способ положить окно в `callback_data`; собирать строку вручную запрещено так же, как в §16.3.

### 19.2 Именованные лимиты расписаний (`domain/schedules.py`)

Ограничения §5 получают имена по той же причине, по которой §18.3 назвал `TIMES_MAX_LENGTH`: мастер обязан отказать пользователю тем же числом, каким его отвергает модель.

```python
WEEKDAYS_MAX_LENGTH: Final = 7
MONTH_DAYS_MAX_LENGTH: Final = 31
INTERVAL_MIN_MINUTES: Final = 5
INTERVAL_MAX_MINUTES: Final = 1440
WINDOW_ATOM_LENGTH: Final = 8
```

Литералы в валидаторах `IntervalSchedule`, `WeeklySchedule` и `MonthlySchedule` заменяются на эти константы. `WINDOW_ATOM_LENGTH` — длина атома §19.1, `HHMMHHMM`.

### 19.3 Клавиатуры (`bot/keyboards/wizard.py`)

| примитив | контракт |
|---|---|
| `weekly_days_kb(selected, lang)` | `weekday_picker_kb` §9 + «Отмена» |
| `monthday_picker_kb(selected, lang)` | числа 1..31 тумблерами, сетка по 7 + «Готово» + «Отмена» |

У чисел месяца нет ключа «список полон»: клавиатура предлагает все `MONTH_DAYS_MAX_LENGTH` чисел, так что превысить лимит нечем. У времён он есть, потому что ручной ввод добавляет времена сверх пресетов.
| `interval_kb(lang)` | `interval_picker_kb` §9 + ручной ввод + «Отмена» |
| `window_kb(lang)` | `window_picker_kb` §9 + ручной ввод + «Отмена» |
| `missing_day_kb(lang)` | Последний день / Пропустить + «Отмена» |

Первые четыре собираются поверх примитивов §9, а не вместо них, как `once_time_kb` §18.4 поверх `time_picker_kb`: пресеты общие, у мастера добавляется только отмена и ручной ввод.

`weekly_days_kb` и `monthday_picker_kb` — тумблеры того же вида, что `daily_times_kb` §18.4: повторное нажатие снимает выбор. Длина списка чисел месяца ограничена `MONTH_DAYS_MAX_LENGTH`, дней недели — `WEEKDAYS_MAX_LENGTH`.

Отмена на каждом экране мастера — общий атом `WizCb(step="confirm", value="no")` §17.4. Требование распространяется на все экраны мастера без исключения, включая экраны интервала и окна: экран без отмены — тупик, из которого пользователь выходит только рестартом.

`window_picker_kb` §9 переводится на `pack_window` §19.1.

### 19.4 Ключи текстов (`bot/render/texts.py`)

`wizard.ask_weekdays`, `wizard.weekdays_none`, `wizard.weekdays_empty`, `wizard.ask_mdays`, `wizard.mdays_none`, `wizard.mdays_empty`, `wizard.ask_missing_day`, `wizard.interval_manual`, `wizard.interval_invalid`, `wizard.window_manual`, `wizard.window_invalid`, `wizard.confirm_weekly`, `wizard.confirm_monthly`, `btn.kind_weekly`, `btn.kind_monthly`, `btn.missing_last_day`, `btn.missing_skip`, `missing.last_day`, `missing.skip`.

У каждого ключа обязательны обе локали и совпадающий набор плейсхолдеров — держится контрактным тестом.

Экран списка времён общий на `daily`, `weekly` и `monthly`, поэтому значение `wizard.ask_times` теряет слова «каждый день»: для расписания по вторникам они врут. Ключ и его плейсхолдеры не меняются, меняется только текст, и второго ключа на тот же экран не заводится.

### 19.5 Модули слайса

Раскладка §3.1 новых файлов не получает: слайс дополняет те, что завёл S3.

```
app/domain/reminders.py         # + сборка weekly, monthly, interval и разбор ручного ввода
app/bot/fsm/reminder_wizard.py  # + состояния weekdays, month_days, on_missing
app/bot/render/wizard.py        # + подтверждения weekly и monthly
```

Публичный API домена дополняется:

```python
def build_weekly_schedule(times: Sequence[time], weekdays: Sequence[int]) -> WeeklySchedule
def build_monthly_schedule(
    times: Sequence[time], days: Sequence[int], on_missing_day: str
) -> MonthlySchedule
def build_interval_schedule(
    every_minutes: int, window_start: time, window_end: time
) -> IntervalSchedule
def parse_user_interval(raw: str) -> int
def parse_user_window(raw: str) -> tuple[time, time]
```

Правила, обязательные к соблюдению:

1. builder-ы ведут себя как `build_daily_schedule` §18.6: дубли схлопываются, порядок не важен, пустой список — `ValidationError`, превышение лимита §19.2 — тоже;
2. `parse_user_interval` принимает целое число минут из `[INTERVAL_MIN_MINUTES, INTERVAL_MAX_MINUTES]`; всё остальное — `ValidationError`;
3. `parse_user_window` принимает `HH:MM-HH:MM` и разбирает обе половины единственным `parse_hhmm` §16.2. Окно через полночь допустимо §5, равные концы означают целые сутки;
4. `interval` создаётся мастером только с окном: расписание без окна контрактом §5 не предусмотрено;
5. функции чистые: ни часов, ни IO, ни импортов вне stdlib и `app/domain`.

### 19.6 Полный набор DST-инвариантов

§10 перечисляет инварианты `next_occurrences`. S7 доводит их до проверяемых утверждений, потому что «полный набор» из §15 иначе не имеет содержания. К уже проверяемым (возрастание, уникальность, полуинтервал `(after, until]`, UTC-aware, `limit`, детерминизм, склейка) добавляются:

1. **`interval`, правило 2.** Соседние моменты **внутри одного окна** отстоят ровно на `every_minutes`. Инвариант проверяется по окнам, а не по всему результату: соседние окна абаттируют только тогда, когда `every_minutes` делит длину окна нацело, и разрыв на стыке — не нарушение, а следствие §5.
2. **`daily`, `weekly`, `monthly`, правила 1 и 3.** Локальное время каждого момента входит в `times`, **либо** это время в дне не существует и момент равен первому существующему. День с переводом часов не пропускается: он и есть предмет проверки.
3. **`weekly`.** Локальный ISO-день каждого момента входит в `weekdays`. Проверяется в локальной таймзоне: в UTC день другой.
4. **`monthly` + `skip`.** Локальное число каждого момента входит в `days`.
5. **`monthly` + `last_day`.** В месяце без нужного числа момент приходится ровно на последний день месяца, и ровно один раз на каждое время из `times`.
6. **`daily`.** Расстояние в днях между локальными датами соседних моментов кратно `every_n_days`.
7. **Правило 4.** Неоднозначное локальное время берётся по раннему смещению — на осеннем переводе в каждой зоне из набора §10.

Набор зон для DST-проверок: `Europe/Berlin` (час, северное полушарие), `America/New_York` (час, другая дата перевода), `Australia/Lord_Howe` (получасовой перевод), `Pacific/Chatham` (получасовое смещение, южное полушарие), `Europe/Moscow` (перевода нет вообще), `UTC`. `Europe/Moscow` в одиночку инвариант не проверяет, о чём предупреждает §10.

---

## 20. Контракт слайса S8 (тихие часы и автоповтор)

Добавлено в `v7`. Раздел append-only, как и весь файл: значения ниже не переименовываются.

Раздел уточняет три строки §7, а не переписывает их: файл append-only, поэтому исправленное чтение живёт здесь и имеет приоритет над прежней формулировкой.

### 20.1 Тихие часы держатся на каждом пути доставки

§1.1 обещает, что доставка внутри тишины сдвигается на конец интервала и не теряется. §7.1 выполняла обещание для запланированного момента, а §7.3 и §7.4 клали в очередь момент, посчитанный от `now`, обратно внутрь тишины. Обещание одно, значит и правило одно: **момент, который назначает доставку заново, проходит через `apply_quiet_hours`**. Таких мест ровно три: материализация §7.1, автоповтор §7.3 и «отложить» §7.4.

Ретрай §7.2 — единственное исключение, и оно остаётся без изменений. Там доставка не назначается заново: она уже наступила и пробивается сквозь сбой транспорта. Отложить её до конца девятичасовой тишины значило бы уронить напоминание совсем, потому что occurrence просрочится по TTL раньше, чем тишина кончится. Backoff считает `domain/retry.py`, и тихие часы туда не заходят.

**§7.1, материализация.** Тихие часы считаются в `users.timezone` владельца на момент планирования, а не в `reminders.timezone`. Последняя — снимок, снятый при создании (§4.2), и переехавший пользователь молчал бы по настенным часам города, из которого уехал. Расписание при этом по-прежнему разворачивается в `reminders.timezone`: снимок отвечает за то, *когда* дело нужно сделать, таймзона пользователя — за то, *когда его можно беспокоить*. Две зоны в одной строке, и путать их нельзя.

**§7.3, строка «Автоповтор», читается так:**

> `sent`, реакции нет, `repeat_after_minutes` задан, `repeats_sent < max_repeats` → `status = 'pending'`, `next_attempt_at = apply_quiet_hours(now, ...)`, `repeats_sent += 1`. Повтор, который тишина переносит на момент не раньше `occurrence.expires_at`, в очередь не ставится вовсе и бюджет не тратит.

Повтор отбрасывается, а не откладывается, потому что к концу тишины occurrence уже просрочен: сообщение пришло бы с кнопками, которые мёртвы в момент отправки, и следующий `sweep` всё равно перевёл бы occurrence в `expired`.

**§7.4, строка `snooze`, читается так:**

> `delivery.status = 'snoozed'`, `snoozed_until = apply_quiet_hours(now + reminder.snooze_minutes, ...)`, `next_attempt_at = snoozed_until`, action-запись.

Откат: если сдвинутый момент не раньше `occurrence.expires_at`, `snoozed_until` остаётся равным `now + snooze_minutes`. Здесь, в отличие от повтора, поздно лучше, чем никогда: повтор — добавка к уже доставленному напоминанию, а «отложить» — явная просьба пользователя, и молча выбросить её значит потерять напоминание вопреки §1.1.

Сдвигается именно `snoozed_until`, а не только `next_attempt_at`: пара обязана оставаться равной. На `snoozed_until` стоит защита от повторного нажатия §7.4, и на нём же построена строка `react.snoozed`, обещающая пользователю время. Разъехавшись, эти двое дают либо принятое второе нажатие, либо обещание, которого продукт не выполнит.

Чьи часы берутся, определяет уровень, на котором стоит момент. `occurrences.fire_at` один на occurrence, поэтому §7.1 считает его по часам владельца. Повтор §7.3 и «отложить» §7.4 пишут `deliveries.next_attempt_at`, а доставка адресована конкретному получателю, поэтому берутся часы получателя (`deliveries.user_id`). У совместного напоминания §10 получателей несколько, и после доставки каждый молчит по своим.

Расхождение между этими двумя уровнями осознанное: сдвигать `fire_at` под каждого получателя нечем, пока `fire_at` один. Если S10 покажет, что владелец глушит доставку соседу, вопрос решается переносом сдвига на `deliveries`, отдельным `CONTRACT GAP`, а не молчаливой правкой §7.1.

### 20.2 Значение тихих часов (`domain/quiet_hours.py`)

```python
@dataclass(frozen=True, slots=True)
class QuietHours:
    tz: ZoneInfo
    start: time | None = None
    end: time | None = None

    @property
    def is_on(self) -> bool: ...
    def covers(self, moment: datetime) -> bool: ...
    def shift(self, moment: datetime) -> datetime: ...
```

Интервал и таймзона ездят вместе, потому что порознь их уже перепутали: §20.1 существует ровно из-за того, что зона бралась не оттуда. `shift` — это `apply_quiet_hours`, `covers` — это `is_quiet`; обе функции остаются публичными и не переименовываются.

`is_on` истинна, когда заданы оба конца, то есть повторяет CHECK `quiet_hours_both_or_none` §4.2. Равные концы `is_on` не отвергает: их отвергает `normalize_quiet_hours` §16.6 на входе, а `covers` на таком интервале ложна по §8.

### 20.3 Чистые решения жнеца (`domain/sweeping.py`)

Жнец получает третий чистый модуль рядом с `domain/planning.py` §7.1 и `domain/dispatching.py` §7.2, по той же причине: сервис владеет транзакцией, SQL и правкой сообщения, а решение о том, *просрочен* ли occurrence и *когда* вернётся неотвеченное напоминание, проверяется property-тестами, а не базой и часами.

```python
@dataclass(frozen=True, slots=True)
class RepeatPlan:
    next_attempt_at: datetime

def is_overdue(status: OccurrenceStatus, expires_at: datetime, now: datetime) -> bool
def decide_repeat(
    *,
    sent_at: datetime | None,
    repeat_after_minutes: int | None,
    repeats_sent: int,
    max_repeats: int,
    expires_at: datetime,
    quiet: QuietHours,
    now: datetime,
) -> RepeatPlan | None
```

Правила, обязательные к соблюдению:

1. `is_overdue` ложна на терминальном статусе §4.1: occurrence, на который ответили, не просрочивают задним числом, иначе ответ пользователя затирается тишиной;
2. граница TTL строгая: `expires_at == now` — ещё не просрочка;
3. `decide_repeat` возвращает `None`, когда `repeat_after_minutes` не задан, `sent_at` пуст, бюджет исчерпан, задержка не вышла или сдвинутый момент не раньше `expires_at`;
4. SQL-предикат репозитория сужает пачку, но решения не принимает. Правило живёт в домене целиком, и запрос — только оптимизация;
5. функции чистые: ни часов, ни IO, ни импортов вне stdlib и `app/domain`.

### 20.4 Бюджет повторов принадлежит occurrence

`repeats_sent` лежит на `occurrences` §4.2, значит бюджет считается на occurrence, а не на доставку: **один прогон `reaper.sweep` тратит ровно один повтор, скольких бы получателей он ни разбудил**. Совместное напоминание §10 отдаёт один и тот же occurrence на каждого получателя, и инкремент в цикле сжёг бы весь бюджет за один прогон.

Отсюда же следует, что `repeats_sent` читается один раз за прогон: значение, поднятое внутри цикла, сделало бы второго получателя похожим на второй повтор.

### 20.5 Отложить теперь знает про тишину (`domain/reactions.py`)

```python
def postpone(
    now: datetime, snooze_minutes: int, *, quiet: QuietHours, expires_at: datetime
) -> datetime

def decide_reaction(
    kind: ActionKind,
    now: datetime,
    snooze_minutes: int,
    *,
    quiet: QuietHours,
    expires_at: datetime,
) -> Reaction
```

`quiet` и `expires_at` обязательны и только именованные: у обоих тип, который легко подставить не на своё место, а цена ошибки — напоминание, ушедшее в тишину или не ушедшее вовсе.

### 20.6 Отображение получателя (`services/recipients.py`)

`domain/` не импортирует `db/` §3, поэтому строка `User` превращается в `QuietHours` в сервисном слое, ровно в одном месте:

```python
def quiet_hours_of(user: User) -> QuietHours
```

Тремя сервисами (`planning`, `dispatching`, `reactions`) пользуется одна функция. Второго вывода тихих часов из строки пользователя где-либо ещё быть не должно: именно дубль этого вывода и брал не ту таймзону.

### 20.7 Модули слайса

Раскладка §3.1 дополняется двумя файлами:

```
app/domain/sweeping.py       # чистые решения reaper.sweep
app/services/recipients.py   # QuietHours из строки пользователя
```

### 20.8 Границы слайса

`repeat_after_minutes` и `max_repeats` экрана не получают: редактирование напоминания приходит в S9 §15, и до него значения берутся из умолчаний §4.2 (`repeat_after_minutes = NULL`, то есть автоповтор выключен). S8 сдаёт механизм, а не настройку.

Период `reaper.sweep` берётся из `PLANNER_INTERVAL_SECONDS`: §7.3 требует шестидесяти секунд, столько же по умолчанию у планировщика, и отдельная переменная окружения на то же число только добавила бы способ их рассинхронизировать.

---

## 21. Контракт слайса S9 (управление напоминаниями)

Добавлено в `v8`. Раздел append-only, как и весь файл: значения ниже не переименовываются.

### 21.1 CallbackData списка (`bot/callbacks.py`)

`PageCb` §6 несёт страницу и не несёт фильтр, а фильтр по категории обязан пережить листание: страница, теряющая фильтр на первой же стрелке, — не фильтр. Паковать категорию в `scope` разделителем запрещено §6, поэтому у экрана списка своя фабрика:

```python
class ListCb(CallbackData, prefix="l"):
    category_id: int    # 0 — без фильтра
    page: int
```

Префикс `l` замораживается наравне с §6. `category_id = 0` — зарезервированное значение «все категории»: `BIGSERIAL` §4.2 начинается с единицы, ноль не может оказаться чужим идентификатором, и второго поля на «фильтра нет» не нужно.

`PageCb(scope="rem")` после S9 не используется ничем: список ездит своей фабрикой, `/today` фильтра не имеет и остаётся на `PageCb(scope="today")`. Значение из `Literal` не убирается — литералы фабрик не переименовываются и не удаляются по той же причине, что и значения enum §4.1.

`paginated_kb` §9 получает единственный именованный параметр, потому что навигация теперь бывает не только `PageCb`:

```python
def paginated_kb(items, scope, page, total_pages, lang=DEFAULT_LANG, *, nav=None)
```

`nav` — функция `int -> CallbackData`, строящая callback стрелки. `None` даёт прежнее `PageCb(scope=scope, page=...)`, поэтому ни один существующий вызов не меняется.

### 21.2 CallbackData редактирования (`bot/callbacks.py`)

Редактирование — новый экран, значит новая фабрика §6:

```python
class EditCb(CallbackData, prefix="e"):
    reminder_id: int
    field: Literal["menu", "title", "note", "category", "schedule", "snooze", "repeat"]
```

| `field` | эффект |
|---|---|
| `menu` | открыть меню редактирования и вернуться в него |
| `title` | спросить новое название |
| `note` | спросить заметку |
| `category` | показать пикер категорий |
| `schedule` | заново пройти ветку расписания мастером §18.1 |
| `snooze` | спросить шаг «отложить» |
| `repeat` | спросить автоповтор |

Префикс `e` замораживается наравне с §6. Фабрика несёт выбор поля и не несёт значения: значение приходит следующим экраном.

Сами значения едут существующей `WizCb`, как создание категории §17.1: напоминание уже лежит в состоянии FSM, и `value` несёт ровно один атом.

| `step` | `value` | эффект |
|---|---|---|
| `snooze` | `1`..`1440` \| `man` | шаг «отложить» |
| `repeat` | `5`..`1440` \| `off` \| `man` | автоповтор либо его выключение |
| `note` | `clear` | снять заметку |
| `filter` | `0`..`<id>` | открыть выбор фильтра, отметив действующий |

Зарезервированные значения: `man` для шагов `snooze` и `repeat`, `off` для шага `repeat`, `clear` для шага `note`. Ни один пресет с ними не совпадает, это держит контрактный тест.

Шаг `filter` живёт здесь, а не в `ListCb` §21.1: открыть пикер — команда, а не страница, и класть команду в поле `page` числом-меткой значило бы перегружать атом ровно так, как запрещает §6. `value` при этом несёт действующий фильтр, потому что пикер обязан отметить, что выбрано сейчас.

Категория при редактировании выбирается общим `category_picker_kb` §9 с `CatCb(action="pick")`: вопрос дословно тот же, что в мастере, и второго пикера на него не заводится. Экраны различает состояние FSM — `ReminderWizard.category` у мастера, `ReminderEdit.category` у редактирования, — а не фабрика.

### 21.3 Пауза и правка расписания снимают запланированное

§7.1 материализует только `active`, поэтому пауза останавливает планировщик. Уже материализованные occurrences она не трогала, и dispatcher §7.2 отправлял их дальше: пауза, после которой напоминание всё равно приходит, паузой не является.

Правило: **уход напоминания из `active` и любая правка расписания снимают ещё не отправленные occurrences.**

1. снимаются `occurrences` в статусе `pending`, у которых ни одна доставка не вышла из `pending`. Строки удаляются, а не помечаются: доставки не было, журналу §4.2 нечего хранить, а `skipped` — реакция пользователя и испортила бы статистику §11;
2. `deliveries` уходят каскадом по FK §4.2, отдельного удаления не требуют;
3. `planned_until` сбрасывается в `NULL`: иначе planner решит, что горизонт уже покрыт, и после возобновления не материализует ничего до его конца;
4. `fired_count` уменьшается на число снятых строк. Бюджет `max_occurrences` §4.2 считает состоявшиеся срабатывания, а снятое не состоялось. Planner всё равно пересчитывает счётчик запросом §7.1, так что колонка просто перестаёт врать карточке;
5. повторный вызов снимает ноль строк и больше ничего не меняет: операция идемпотентна, как цикл воркера §10.

Уже отправленное (`sent`) не трогается. Пользователь смотрит на сообщение с живыми кнопками, и отнимать их задним числом пауза не вправе: такое occurrence доживает до реакции §7.4 или до просрочки §7.3.

### 21.4 Границы правки напоминания

Правка меняет: `title`, `note`, `category_id`, `schedule` вместе с `schedule_kind`, `snooze_minutes`, `repeat_after_minutes`.

Правка не меняет: `timezone`, `starts_at`, `ends_at`, `max_occurrences`, `max_repeats`, `owner_id`. Экранов для них S9 не заводит. `timezone` — отдельный случай: это снимок §4.2, в котором уже развёрнуто расписание, и подмена его задним числом сдвинула бы каждое будущее срабатывание, ничего не сказав пользователю. Переезд владельца меняет тихие часы §20.1 и не меняет расписаний.

Новое расписание проходит те же ворота, что и создание §18.6: пустое будущее — `ScheduleExhaustedError`, и строка остаётся прежней. Новая категория проверяется как при создании: архивная — `NotFoundError`, чужая — `PermissionDeniedError`.

Архивное напоминание не редактируется, не ставится на паузу и не возобновляется: `PermissionDeniedError`. Список §21.6 архивные не показывает, так что нажатие приходит только со старого экрана, и оживлять исчерпанное напоминание §7.1 такому нажатию нельзя.

Удаление разрушающее и каскадное §4.2, поэтому подтверждается. Архивация напоминаний экрана в S9 не получает: её делает planner, когда расписание исчерпано §7.1.

### 21.5 Ограничения «отложить» и автоповтора (`domain/contracts.py`)

```python
SNOOZE_MIN_MINUTES: Final = 1
SNOOZE_MAX_MINUTES: Final = 1440
REPEAT_MIN_MINUTES: Final = 5
REPEAT_MAX_MINUTES: Final = 1440
```

Верх у обоих — сутки, как у интервала §19.2: значения едут в `SMALLINT` §4.2, и шаг длиннее суток означает, что пользователь ошибся экраном. Низ у повтора — те же пять минут, что у интервала: повтор чаще, чем просыпается `reaper.sweep` §20.8, всё равно не состоится.

Оба значения пользователь может задать больше, чем `OCCURRENCE_TTL_MINUTES` §11.1. Это его право и не поломка контракта: occurrence успеет просрочиться §7.3, и отложенная доставка не выйдет. Домен границу TTL не знает, потому что TTL — настройка окружения, а домен настроек не читает §3.

### 21.6 Клавиатуры (`bot/keyboards/reminders.py`)

| примитив | контракт |
|---|---|
| `reminder_list_kb(items, category_id, page, total_pages, lang)` | страница списка поверх `paginated_kb` §9 + «Фильтр» |
| `reminder_filter_kb(categories, current, lang)` | «Все» и категории, текущая помечена |
| `reminder_card_kb(reminder_id, status, category_id, lang)` | Пауза либо Возобновить, Изменить, Удалить, Назад в список |
| `reminder_edit_kb(reminder_id, lang)` | шесть полей §21.4 + Назад на карточку |
| `snooze_picker_kb(lang)` | пресеты минут + ручной ввод + Отмена |
| `repeat_picker_kb(lang)` | пресеты минут + «Выключить» + ручной ввод + Отмена |
| `note_kb(lang)` | «Очистить» + Отмена |
| `today_kb(page, total_pages, lang)` | навигация `paginated_kb` §9 без строк |

`reminder_list_kb` и `today_kb` собираются поверх `paginated_kb`, а не вместо неё, ровно как `category_list_kb` §17.4. `note_kb` нужна отдельно, потому что пустое сообщение в Telegram не отправить: снять заметку можно только кнопкой.

`reminder_card_kb` показывает ровно одну кнопку из пары Пауза/Возобновить, ту, которая меняет состояние. Кнопка, не меняющая ничего, врёт о состоянии, а карточка — единственное место, где пользователь это состояние читает. Она же несёт `category_id`, чтобы «Назад» вернуло в тот отфильтрованный список, из которого пользователь пришёл.

`confirm_kb("delete", reminder_id)` §9 ведёт «Отмену» на `RemCb(action="open")`, а не на общий атом §17.4. Отмена возвращает туда, откуда пришла, а у удаления, в отличие от создания и архивации категории, есть куда возвращаться — карточка того же напоминания. Ветки `create` и `archive` не меняются.

Отмена на экранах редактирования — общий атом `WizCb(step="confirm", value="no")` §17.4, как на всех экранах мастера §19.3.

### 21.7 Ключи текстов (`bot/render/texts.py`)

`list.filter`, `list.filter_all`, `list.paused_mark`, `schedule.once`, `schedule.daily`, `schedule.weekly`, `schedule.monthly`, `schedule.interval`, `reminder.note`, `reminder.schedule`, `reminder.repeat_on`, `reminder.repeat_off`, `reminder.paused`, `reminder.resumed`, `reminder.confirm_delete`, `reminder.deleted`, `reminder.archived_readonly`, `edit.menu`, `edit.ask_title`, `edit.ask_note`, `edit.ask_category`, `edit.ask_snooze`, `edit.ask_repeat`, `edit.pick_kind`, `edit.saved`, `edit.snooze_invalid`, `edit.repeat_invalid`, `edit.note_invalid`, `edit.repeat_off`, `edit.cancelled`, `today.title`, `today.empty`, `today.item`, `today.mark_pending`, `today.mark_done`, `today.mark_skipped`, `today.mark_missed`, `btn.filter`, `btn.all_categories`, `btn.pause`, `btn.resume`, `btn.edit`, `btn.delete`, `btn.to_list`, `btn.edit_title`, `btn.edit_note`, `btn.edit_category`, `btn.edit_schedule`, `btn.edit_snooze`, `btn.edit_repeat`, `btn.repeat_off`, `btn.note_clear`.

`reminder.card` из `v1` получает два плейсхолдера, `{schedule}` и `{note}`: карточка — экран, на котором пользователь решает, что менять, а расписания и заметки на ней не было видно. Ключ и его имя не меняются, второй карточки не заводится.

`list.item` из `v1` получает плейсхолдер `{mark}`: список после S9 показывает и приостановленные напоминания, и строка, не отличающая их от активных, врёт о состоянии так же, как врала бы лишняя кнопка на карточке §21.6.

Ключи `schedule.*` описывают расписание одной строкой для карточки. Подтверждения мастера `wizard.confirm_*` §18.5 на эту роль не годятся: они задают вопрос, а карточка сообщает факт.

У каждого ключа обязательны обе локали и совпадающий набор плейсхолдеров — держится контрактным тестом.

`render_reminder_card` и `render_reminder_list` §9 обновляются вместе с ключами: примитивы и строки — общие файлы §11.2 и живут в одном PR ядра. `render_schedule_summary(schedule, lang)` появляется рядом с карточкой в `bot/render/reminder.py`.

### 21.8 Модули слайса

Раскладка §3.1 дополняется четырьмя файлами, из которых клавиатуры §21.6 пишет тимлид, а остальные — слайс S9:

```
app/bot/keyboards/reminders.py   # список, карточка, редактирование, пикеры
app/bot/fsm/reminder_edit.py     # состояния ReminderEdit
app/bot/render/today.py          # рендер сегодняшнего дня
app/bot/handlers/manage.py       # карточка, пауза, редактирование, удаление
```

`/list` и `/today` живут в `app/bot/handlers/lists.py` §3.1: оба списки. Карточка и всё, что она открывает, живёт отдельно, потому что мастер `app/bot/handlers/reminders.py` уже занят созданием и третья роль в одном модуле его не улучшит.

Публичный API домена дополняется:

```python
def parse_user_snooze(raw: str) -> int
def parse_user_repeat(raw: str) -> int
def local_day_bounds(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]
```

Правила, обязательные к соблюдению:

1. `parse_user_snooze` и `parse_user_repeat` принимают целое число минут из своих отрезков §21.5, всё остальное — `ValidationError`, как `parse_user_interval` §19.5;
2. `local_day_bounds` возвращает полуинтервал `[начало дня, начало следующего дня)` в UTC. Границы разрешаются тем же `to_utc`, что и расписания: несуществующая полночь сдвигается вперёд §5.1.3, неоднозначная берётся по раннему смещению §5.1.4. Сутки поэтому не всегда двадцать четыре часа, и `/today` обязан это переживать;
3. соседние дни стыкуются без зазора и без нахлёста: конец дня равен началу следующего;
4. функции чистые: ни часов, ни IO, ни импортов вне stdlib и `app/domain`.

### 21.9 Границы слайса

`/today` показывает доставки, адресованные пользователю, а не occurrences его напоминаний. Уровень выбран под S10 §15: у совместного напоминания получателей несколько, и «мой день» у каждого свой. Владелец сам себе получатель §7.1, так что до S10 разницы не видно.

Пагинация `/today` идёт `PageCb(scope="today")` без фильтра: день и так короткий, а фильтр по категории на нём отвечал бы на вопрос, которого никто не задаёт.

Приглашение другого пользователя, отписка и роль `watcher` — это S10, и экранов в S9 не получают.

---

## 22. Контракт слайса S10 (совместные напоминания)

Добавлено в `v9`. Раздел append-only, как и весь файл: значения ниже не переименовываются.

### 22.1 Приглашение — строка в БД, а не подпись

Deep-link `t.me/<bot>?start=inv_<token>` §15 нужно чем-то выдать и чем-то отозвать. Подписанный токен, выведенный из `reminder_id` секретом, не отзывается и не истекает: ссылка, один раз попавшая в общий чат, работает вечно. Поэтому приглашение — строка, и у неё есть срок и признак отзыва.

**reminder_invites**

| поле | тип | описание |
|---|---|---|
| id | BIGSERIAL PK | |
| reminder_id | BIGINT NOT NULL FK reminders(id) ON DELETE CASCADE | |
| token | TEXT NOT NULL | тело deep-link без префикса |
| created_by | BIGINT NOT NULL FK users(id) ON DELETE CASCADE | владелец на момент выдачи |
| expires_at | TIMESTAMPTZ NOT NULL | докуда ссылка живёт |
| revoked_at | TIMESTAMPTZ NULL | отозвана владельцем |
| created_at | TIMESTAMPTZ NOT NULL DEFAULT now() | |

Индексы: `UNIQUE (token)`; `UNIQUE (reminder_id) WHERE revoked_at IS NULL` — живое приглашение у напоминания одно.

Из частичного уникального индекса следует правило выдачи: **новая ссылка отзывает предыдущую**. Две живые ссылки на одно напоминание означали бы, что отзыв одной ничего не отзывает, и владелец, нажавший «Отозвать», остался бы с открытым доступом.

Приглашение многоразовое, пока живо. Ссылка, брошенная в семейный чат и принятая двумя людьми, — обычный случай, а не злоупотребление. Ограничивает не число нажатий, а `REMINDER_WATCHERS_MAX` §22.4.

### 22.2 Токен и deep-link (`domain/sharing.py`)

Telegram отдаёт стартовый payload длиной до 64 символов из алфавита `A-Za-z0-9_-`. Токен — `base64url` без выравнивания, его алфавит подмножество разрешённого, и `inv_` перед ним разбирается срезом фиксированной длины, а не поиском разделителя.

```python
INVITE_DEEP_LINK_PREFIX: Final = "inv_"

def new_invite_token(entropy: bytes) -> str
def parse_invite_payload(raw: str) -> str
def build_invite_payload(token: str) -> str
def build_invite_link(bot_username: str, token: str) -> str
def invite_state(expires_at: datetime, revoked_at: datetime | None, now: datetime) -> InviteState
def check_join(role: RecipientRole | None, watchers: int, limit: int) -> None
```

`InviteState` — `StrEnum` из `live | expired | revoked`. Отозванное приглашение остаётся отозванным и после истечения срока: причина отказа принадлежит владельцу, а не часам.

Случайность в домен не заходит. `new_invite_token` получает готовые байты и превращает их в строку детерминированно, как чистые функции получают `now` из `Clock` §8. Байты берёт сервис.

Правила, обязательные к соблюдению:

1. `parse_invite_payload` принимает ровно `INVITE_DEEP_LINK_PREFIX` + токен длины `INVITE_TOKEN_LENGTH` из алфавита base64url; всё остальное — `ValidationError`;
2. `build_invite_payload` и `parse_invite_payload` — обратные друг другу на любом валидном токене;
3. полный payload не длиннее `DEEP_LINK_MAX_LENGTH`, иначе Telegram обрежет ссылку молча;
4. функции чистые: ни часов, ни IO, ни случайности, ни импортов вне stdlib и `app/domain`.

### 22.3 CallbackData совместного доступа (`bot/callbacks.py`)

Совместный доступ — новый экран, значит новая фабрика §6:

```python
class ShareCb(CallbackData, prefix="i"):
    reminder_id: int
    action: Literal["open", "invite", "revoke", "accept", "decline", "leave", "confirm_leave"]
```

| `action` | кто нажимает | эффект |
|---|---|---|
| `open` | владелец и наблюдатель | открыть экран доступа: у владельца — получатели и ссылка, у наблюдателя — карточка и отписка |
| `invite` | владелец | выдать ссылку, отозвав прежнюю |
| `revoke` | владелец | отозвать живую ссылку |
| `accept` | приглашённый | принять, `accepted_at = now` |
| `decline` | приглашённый | отказаться, строка получателя снимается |
| `leave` | наблюдатель | спросить подтверждение отписки |
| `confirm_leave` | наблюдатель | отписаться |

Префикс `i` замораживается наравне с §6. Фабрика несёт `reminder_id`, а не токен: к моменту любого из этих нажатий строка получателя уже существует §22.5, и класть в `callback_data` двадцатидвухсимвольный токен незачем.

`PageCb.scope` §6 получает значение `shared`. Список общих напоминаний фильтра не имеет, поэтому своя фабрика ему не нужна, в отличие от списка своих §21.1. Набор значений `scope` append-only, как и у enum §4.1.

`confirm_kb(action, entity_id)` §9 принимает четвёртое действие `leave`; кнопка «Да» шлёт `ShareCb(action="confirm_leave")`, «Отмена» — `ShareCb(action="open")`. Отмена возвращает туда, откуда пришла, по тому же правилу, что и у удаления §21.6: у отписки есть куда возвращаться.

### 22.4 Ограничения совместного доступа (`domain/contracts.py`)

```python
INVITE_TOKEN_BYTES: Final = 16
INVITE_TOKEN_LENGTH: Final = 22
INVITE_TTL_HOURS: Final = 72
REMINDER_WATCHERS_MAX: Final = 10
DEEP_LINK_MAX_LENGTH: Final = 64
```

`INVITE_TOKEN_LENGTH` — длина `base64url` от `INVITE_TOKEN_BYTES` без выравнивания, и контрактный тест держит эти два числа согласованными: разъехавшись, они дали бы ссылку, которую собственный разбор отвергает.

`REMINDER_WATCHERS_MAX` считает только наблюдателей, владелец в лимит не входит. Ограничение нужно потому, что каждый принявший умножает доставки на каждое occurrence: ссылка, утёкшая в публичный чат, без лимита превращает одно напоминание в рассылку.

`DEEP_LINK_MAX_LENGTH` дублирует ограничение Telegram по той же причине, по которой §17.2 дублирует CHECK: домен обязан отвергнуть значение раньше, чем его молча обрежет транспорт.

### 22.5 Принятие проходит через строку получателя

Deep-link не подписывает пользователя молча. Переход по ссылке заводит строку в `reminder_recipients` с `role = 'watcher'` и `accepted_at IS NULL`, и только нажатие «Принять» проставляет `accepted_at`. Схема §4.2 ровно это и описывает: `accepted_at` нулевой, а planner §7.1 считает получателем только принявшего.

Строка, а не состояние FSM, потому что приглашённый чаще всего видит бота впервые. Его встречает онбординг §16, и вопрос о таймзоне обязан прийти раньше вопроса о приглашении: без таймзоны напоминание нечем показать. Приглашение поэтому переживает онбординг лёжа в БД, а предложение принять показывается сразу после того, как таймзона сохранена.

Порядок отказов при переходе по ссылке, сверху вниз:

| ситуация | ответ |
|---|---|
| payload не разбирается | `share.link_invalid` |
| токен неизвестен | `share.link_unknown` |
| приглашение отозвано или истекло | `share.link_dead` |
| нажал владелец | `share.own_invite` |
| уже принял | `share.already_in` + карточка |
| наблюдателей уже `REMINDER_WATCHERS_MAX` | `share.full` |
| остальное | карточка напоминания + Принять / Отклонить |

Владелец отдельной строкой не проверяется на лимит: он не наблюдатель.

### 22.6 Принятие и отписка правят очередь

Planner §7.1 заводит доставки в момент материализации, поэтому принявший позже наблюдатель ничего не получил бы по уже материализованным occurrences. Симметрично, отписавшийся продолжал бы получать то, что уже стоит в очереди.

**Принятие достраивает доставки** по occurrences напоминания в статусе `pending` с `fire_at > now`, по одной на нового получателя. Идемпотентно ключом `(occurrence_id, user_id)` §4.2.

Граница именно `fire_at > now`, а не «все pending»: occurrence с прошедшим `fire_at` уже разбирается диспетчером, и наблюдатель, принявший приглашение минуту назад, получил бы напоминание о деле, срок которого прошёл до его прихода.

**Отписка снимает доставки** этого получателя по этому напоминанию, находящиеся в статусе `pending`, и удаляет строку получателя. Правило то же, что у паузы §21.3, и по той же причине: `sent` не трогается, потому что на чьём-то экране живые кнопки, а `snoozed` — прямая просьба пользователя.

Обе операции идемпотентны: повторный вызов достраивает и снимает ноль строк и больше ничего не меняет.

Отклонение приглашения удаляет строку получателя. Доставок у неё быть не может: `accepted_at` не проставлялся, значит planner её ни разу не видел.

### 22.7 Клавиатуры (`bot/keyboards/share.py`)

| примитив | контракт |
|---|---|
| `share_menu_kb(reminder_id, lang, *, has_invite)` | Пригласить, Отозвать ссылку только при живой ссылке, Назад на карточку |
| `invite_offer_kb(reminder_id, lang)` | Принять / Отклонить |
| `shared_list_kb(items, page, total_pages, lang)` | страница поверх `paginated_kb` §9 со `scope = "shared"` |
| `shared_card_kb(reminder_id, lang)` | Отписаться + Назад к списку |

`share_menu_kb` рисует «Отозвать» только когда есть что отзывать, по тому же правилу, что и `reminder_card_kb` §21.6 рисует одну кнопку из пары: кнопка, не меняющая ничего, врёт о состоянии.

`reminder_card_kb` §21.6 получает седьмую кнопку «Доступ» на `ShareCb(action="open")`. Экран доступа принадлежит напоминанию, и попадать на него иначе как с его карточки незачем.

### 22.8 Ключи текстов (`bot/render/texts.py`)

`share.menu`, `share.recipients`, `share.recipients_none`, `share.recipient_item`, `share.pending_mark`, `share.invite_link`, `share.invite_revoked`, `share.no_invite`, `share.link_invalid`, `share.link_unknown`, `share.link_dead`, `share.own_invite`, `share.already_in`, `share.full`, `share.offer`, `share.accepted`, `share.declined`, `share.confirm_leave`, `share.left`, `share.list_title`, `share.list_empty`, `share.list_item`, `share.card`, `share.owner`, `share.unknown_user`, `reminder.shared`, `btn.share`, `btn.invite`, `btn.revoke`, `btn.accept`, `btn.decline`, `btn.leave`, `btn.to_shared`.

`reminder.card` получает третий плейсхолдер `{shared}`: карточка — единственный экран, где владелец читает состояние напоминания §21.6, и напоминание, которое уходит ещё троим, обязано об этом говорить. Ключ и его имя не меняются, второй карточки не заводится. `render_reminder_card` §9 получает параметр `watchers: int = 0`, поэтому ни один существующий вызов не ломается.

`share.unknown_user` нужен потому, что `users.username` нулевой §4.2, а `first_name` бывает пустым: получателя в списке всегда есть чем назвать.

У каждого ключа обязательны обе локали и совпадающий набор плейсхолдеров — держится контрактным тестом.

### 22.9 Имя бота в конфигурации

```
BOT_USERNAME=reminder_bot
```

Ссылку собирает `build_invite_link` §22.2, и имя бота ей неоткуда взять, кроме конфигурации: `getMe` — сетевой вызов, а в `USE_FAKE_BOT=true` §11.1 сети нет вообще. Значение читается там же, где остальное окружение, — в `app/core/config.py` §11.1, без `@`.

Значение в `.env.example` — заглушка для локального запуска. Деплой обязан подставить настоящее имя: несовпадение даёт ссылку, ведущую к другому боту, и обнаруживается только на живом пользователе.

### 22.10 Модули слайса

Раскладка §3.1 дополняется шестью файлами, из которых модель, миграцию и клавиатуры §22.7 пишет тимлид, а остальные — слайс S10:

```
app/db/models/invite.py            # ReminderInvite
app/db/repositories/invites.py     # InvitesRepository
app/domain/sharing.py              # токен, deep-link, состояние приглашения
app/services/sharing.py            # SharingService
app/bot/keyboards/share.py         # экраны доступа
app/bot/handlers/share.py          # deep-link, приглашение, принятие, отписка
app/bot/render/share.py            # экран доступа, список общих, карточка
```

`RecipientsRepository` §3.1 дополняется запросами о получателях: получить строку, завести незапрошенную, принять, снять, перечислить получателей напоминания и напоминания пользователя, посчитать наблюдателей.

`/shared` живёт в `handlers/share.py`, а не в `handlers/lists.py` §21.8: список общих напоминаний открывает только экраны доступа, и разносить его с ними по разным модулям значило бы связать два модуля ради одной команды.

`domain/errors.py` дополняется `InviteExpiredError` и `RecipientLimitError`. Неизвестный токен — `NotFoundError`, своё приглашение — `PermissionDeniedError`, неразбираемый payload — `ValidationError`: новых имён на то, что уже названо, не заводится.

### 22.11 Границы слайса

Тихие часы остаются такими, как их оставил §20.1: `occurrences.fire_at` сдвигается по часам владельца, а `deliveries.next_attempt_at` при повторе и «отложить» — по часам получателя. S10 это расхождение не трогает и не прячет. §20.1 прямо назвал условие пересмотра — владелец глушит доставку соседу, — и решается оно переносом сдвига на `deliveries` отдельным `CONTRACT GAP`, а не заодно внутри слайса.

Наблюдатель получает напоминание и реагирует на него: реакция §7.4 адресована delivery, то есть конкретному получателю, и occurrence становится `done`, только когда терминальны все доставки. Менять напоминание, ставить его на паузу и удалять по-прежнему может только владелец §21.4: наблюдатель видит карточку и отписывается, но не редактирует чужое.

Владелец не снимает наблюдателя сам: у него есть отзыв ссылки, а у наблюдателя — отписка. Экрана «выгнать получателя» S10 не заводит, и `role` после создания строки не меняется.

Приглашение в `/list` и в `/today` не видно: `/list` показывает свои напоминания §21.1, `/today` — свои доставки §21.9, и принятое напоминание попадает во второй список само, потому что доставка у наблюдателя своя.

Статистика по общему напоминанию — это S11 §15.

---

## 23. Контракт слайса S11 (статистика)

Добавлено в `v10`. Раздел append-only, как и весь файл: значения ниже не переименовываются.

### 23.1 Статистика читает журнал, а не очередь

Источник — `delivery_actions` §4.2, и только он. Журнал append-only, строки не обновляются и не удаляются, поэтому статистика воспроизводима: два запроса на одних и тех же данных дают один ответ. Очередь для этого не годится вовсе. `deliveries` и `occurrences` живут: пауза §21.3 и отписка §22.6 удаляют незапущенные строки, и посчитанная по ним доля выполненных менялась бы задним числом от нажатия на «Пауза».

Правила счёта, обязательные к соблюдению:

1. **Исход** — реакция из набора `done | skip | auto_expire`. `snooze` исходом не является: он переносит напоминание, а не закрывает его, и попав в знаменатель превращал бы откладывание в провал;
2. **Знаменатель** — исходы, а не запланированные срабатывания. Доставка, которая ещё стоит в очереди, о пользователе ничего не говорит, а `failed` и `blocked` §4.1 говорят о транспорте, а не о нём;
3. **Окна 7 и 30 дней** — скользящие, полуинтервал `(now - N суток, now]`. Не «последние семь календарных дней»: календарное окно скачет на переводе часов и на переезде пользователя, а доля выполненных не должна меняться от того, что человек сменил таймзону;
4. **Серия** считается по локальным суткам получателя: день засчитан, если в нём есть хотя бы один `done`. Незакрытый сегодняшний день серию не рвёт, потому что он ещё не прожит;
5. **Статистика принадлежит получателю, а не владельцу.** Строка журнала адресована `delivery_actions.user_id`, поэтому у наблюдателя §22.11 своя серия и своя доля по общему напоминанию. Складывать их владельцу нельзя: он увидел бы чужую дисциплину как свою;
6. **Разбивка по категориям** берётся через `deliveries → occurrences → reminders.category_id`. Категория читается по напоминанию на момент запроса, а не запоминается в журнале: правка категории §21.4 переносит историю напоминания целиком, и разорванная надвое серия соврала бы обеим категориям.

### 23.2 Публичный API домена (`domain/stats.py`)

```python
STATS_HISTORY_DAYS: Final = 30
STATS_WINDOW_DAYS: Final[tuple[int, int]] = (7, 30)

@dataclass(frozen=True, slots=True)
class ActionRecord:
    happened_at: datetime
    kind: ActionKind
    category_id: int = 0

@dataclass(frozen=True, slots=True)
class CategoryStats:
    category_id: int
    current_streak: int
    longest_streak: int
    last_7_days: PeriodStats
    last_30_days: PeriodStats

@dataclass(frozen=True, slots=True)
class StatsSummary:
    current_streak: int
    longest_streak: int
    last_7_days: PeriodStats
    last_30_days: PeriodStats
    by_category: tuple[CategoryStats, ...] = ()
```

`STATS_HISTORY_DAYS` — глубина, на которую сервис читает журнал, и она же самое длинное окно §23.1.3. Два числа порознь означали бы месячную долю, посчитанную по неделе данных.

Правила, обязательные к соблюдению:

1. `build_summary` чистая: ни часов, ни IO, ни импортов вне stdlib и `app/domain`. `now` приходит аргументом, как всюду в домене §8;
2. порядок записей на результат не влияет, дубли записей не схлопываются: журнал их и не содержит;
3. `by_category` детерминирована и отсортирована по `category_id`. Категория попадает в разбивку, когда у неё есть хотя бы один исход внутри истории;
4. сумма `total` по разбивке равна `total` общего окна: каждый исход принадлежит ровно одной категории;
5. серия категории не превышает общую серию, а `current_streak` не превышает `longest_streak`. Первое следует из второго: день, засчитанный категории, засчитан и целому;
6. пустая история — нулевая сводка, а не ошибка. Доля выполненных на нулевом знаменателе равна нулю, а не единице: ничего не сделано, а не всё.

### 23.3 CallbackData экрана статистики (`bot/callbacks.py`)

Статистика — новый экран, значит новая фабрика §6:

```python
class StatCb(CallbackData, prefix="t"):
    category_id: int    # 0 — весь срез
    page: int
```

Префикс `t` замораживается наравне с §6. `category_id = 0` означает «все категории» ровно так же, как в `ListCb` §21.1, и той же константой `NO_CATEGORY_FILTER`: второго способа сказать «фильтра нет» не заводится.

Разбивка по категориям листается, поэтому `page` едет рядом с фильтром по той же причине, по которой они едут вместе в `ListCb`: страница, теряющая срез на первой же стрелке, врёт о том, что показывает. На экране одной категории `page` равен нулю.

Своего пикера у статистики нет. Категории — это и есть строки разбивки, и каждая строка сама открывает свой срез: экран, который уже перечисляет категории, не нуждается во втором экране, который перечисляет их снова. Шаг `filter` у `WizCb` §21.2 принадлежит списку напоминаний и здесь не переиспользуется: два роутера на один атом разошлись бы по состоянию FSM, а не по смыслу.

### 23.4 Клавиатуры (`bot/keyboards/stats.py`)

| примитив | контракт |
|---|---|
| `stats_kb(items, page, total_pages, lang)` | страница разбивки поверх `paginated_kb` §9 со стрелками на `StatCb` |
| `stats_card_kb(lang)` | «Ко всем категориям» на `StatCb(category_id=0, page=0)` |

`stats_kb` собирается поверх `paginated_kb`, а не вместо неё, ровно как `category_list_kb` §17.4 и `reminder_list_kb` §21.6. Стрелки строятся параметром `nav` §21.1, потому что листается `StatCb`, а не `PageCb`.

`PageCb.scope` и алиас `Scope` в `bot/keyboards/pagination.py` получают значение `stats`. Стрелки на нём не строятся никогда: экран листается `StatCb`, и значение остаётся неиспользованным ровно так же, как `rem` после S9 §6. Заведено оно затем, чтобы два списка оставались одним: `paginated_kb` принимает `scope` позиционно, и экран, назвавший чужой scope ради параметра, который всё равно перекрыт, врал бы о том, что листает.

Кнопки «Отмена» ни у одного из экранов нет: статистика ничего не меняет, отменять на ней нечего, и экран одной категории возвращается кнопкой ко всем.

### 23.5 Недельный дайджест — четвёртый цикл воркера

```python
class JobId(StrEnum):
    DIGEST_SEND = "digest.send"
```

Enum append-only §4.1. Джоб описан как контракт и тестируется как джоб §7.

- Период: `PLANNER_INTERVAL_SECONDS`. Отдельной переменной на то же число не заводится по причине §20.8: два имени для одного периода дают только способ их рассинхронизировать.
- Вход: пользователи с `onboarded_at IS NOT NULL`, `is_blocked = false`, `digest_enabled = true`, у которых наступил недельный момент §23.8 и он новее `digest_sent_at`. Пачка ограничена `DIGEST_BATCH_SIZE`.
- Действие: собрать сводку §23.2 за неделю, отправить одним сообщением через `BotGateway`, проставить `users.digest_sent_at = недельный момент`.
- **Идемпотентность** держится на `digest_sent_at`, и в него пишется сам недельный момент, а не `now`. Момент отправки плавает: цикл просыпается раз в минуту, тишина §23.6 сдвигает отправку, ретрай сдвигает её ещё раз. Записанный `now` пришлось бы сравнивать с началом недели через арифметику, а записанный момент сравнивается с ним же. Повторный прогон на том же входе не отправляет ни одного сообщения.
- **Пустая неделя не отправляется, но отмечается.** Дайджест без единого исхода — это сообщение «ты ничего не делал», которое бот шлёт человеку, ничего у него не спросив. Отметка при этом ставится: без неё цикл возвращался бы к этому пользователю каждую минуту до конца недели.
- Дайджест не занимает `deliveries` и не создаёт occurrence. Это не напоминание: у него нет расписания, нет кнопок реакции, нет срока и нет строки в журнале §23.1. Считать его в статистике было бы двойным счётом самой статистики.

Ошибки транспорта разбираются по классам `ErrorClass` §8, и таблица короче §7.2, потому что ретраить дайджест дольше недели незачем:

| класс | реакция |
|---|---|
| `forbidden` | `users.is_blocked = true`, отметка ставится, ретраев нет |
| `bad_request` | отметка ставится, ретраев нет, лог уровня error |
| `retry_after`, `transient` | отметка не ставится, следующий тик повторит |

Сбой на одном пользователе не роняет пачку: остальные в ней ни при чём, а следующий тик всё равно наступит через минуту.

### 23.6 Дайджест проходит через тихие часы

§20.1 назвал три пути, назначающие доставку заново, и потребовал, чтобы каждый проходил через `apply_quiet_hours`. Дайджест — четвёртый такой путь, и правило распространяется на него без исключений: момент дайджеста §23.8 разрешается через `QuietHours.shift` §20.2 по часам самого пользователя.

Исключение §20.1 — ретрай — на дайджест не переносится: там доставка уже наступила и пробивалась сквозь сбой транспорта, здесь момент назначается впервые. Обратный довод §20.1 — «occurrence просрочится по TTL раньше, чем тишина кончится» — тоже не переносится: у дайджеста TTL нет, ему некуда просрочиться, и сдвиг на конец тишины его не теряет.

Сдвиг откладывает отправку и не меняет, какой это дайджест: ключом идемпотентности §23.5 остаётся неотодвинутый недельный момент. Иначе тишина, кончающаяся уже в следующих сутках, выдала бы за неделю два дайджеста.

### 23.7 Схема: две колонки у пользователя

**users** §4.2 дополняется:

| поле | тип | описание |
|---|---|---|
| digest_enabled | BOOLEAN NOT NULL DEFAULT true | пользователь согласен получать дайджест |
| digest_sent_at | TIMESTAMPTZ NULL | недельный момент последнего отправленного дайджеста, не время отправки |

`digest_enabled` заведён вместе с самим дайджестом, а не отложен: еженедельное сообщение без кнопки «выключить» — дефект, а не фича, и заводить его отдельной миграцией позже значит неделю рассылать то, от чего нельзя отписаться. Умолчание `true`, потому что дайджест — обещанная §15 часть продукта, а не подписка.

`digest_sent_at` нулевой у нового пользователя. Это не значит «дайджест просрочен»: первый же цикл разберёт ближайший прошедший момент и либо отправит сводку, либо отметит пустую неделю §23.5.

`SetCb.field` §16.3 получает значение `digest`; набор полей append-only, как и у `PageCb.scope` §22.3.

| `field` | допустимые `value` | эффект |
|---|---|---|
| `digest` | `on` \| `off` | включить или выключить недельный дайджест |

Зарезервированные значения: `on`, `off`. Отдельного экрана дайджест не получает: вопрос ровно один и ответов ровно два, а экран из одного тумблера — лишний шаг между вопросом и ответом.

### 23.8 Чистый модуль дайджеста (`domain/digest.py`)

Слайс получает четвёртый чистый модуль рядом с `domain/planning.py`, `domain/dispatching.py` и `domain/sweeping.py` §20.3, по той же причине: сервис владеет транзакцией, SQL и отправкой, а решение о том, *какой* дайджест сейчас должен уйти и *когда* он наступил, проверяется property-тестами, а не базой и часами.

```python
@dataclass(frozen=True, slots=True)
class DigestWindow:
    start: datetime    # UTC, исключительно
    end: datetime      # UTC, включительно

def last_digest_moment(now: datetime, tz: ZoneInfo, weekday: int, hour: int) -> datetime
def digest_window(moment: datetime, tz: ZoneInfo) -> DigestWindow
def digest_due_at(
    now: datetime,
    tz: ZoneInfo,
    *,
    weekday: int,
    hour: int,
    sent_at: datetime | None,
    quiet: QuietHours,
) -> datetime | None
```

Правила, обязательные к соблюдению:

1. `last_digest_moment` — ближайший локальный `weekday` в `hour:00`, не позже `now`. День недели по ISO, понедельник = 1, как в §5. Локальный момент разрешается тем же `to_utc`, что и расписания: несуществующий час сдвигается вперёд §5.1.3, неоднозначный берётся по раннему смещению §5.1.4;
2. соседние моменты отстоят ровно на одну **локальную** неделю, а не на 168 часов: на переводе часов неделя короче или длиннее, и настенное время дайджеста выигрывает так же, как оно выигрывает у `daily` §5.1.1;
3. `digest_window` — семь локальных суток, кончающихся моментом. Окна соседних недель стыкуются без зазора и без нахлёста, как сутки `local_day_bounds` §21.8: `digest_window(m).start` равен `digest_window(предыдущий m).end`;
4. `digest_due_at` возвращает **неотодвинутый** недельный момент, когда дайджест за него ещё не отмечен и сдвинутый тишиной момент §23.6 уже наступил; во всех прочих случаях `None`. Возвращённое значение — и ключ идемпотентности §23.5, и конец окна §23.8.3;
5. `sent_at`, равный моменту, — уже отправлено. Граница нестрогая, в отличие от TTL §20.3.2: отметка означает состоявшийся дайджест, а не приближение к нему;
6. функции чистые: ни часов, ни IO, ни импортов вне stdlib и `app/domain`.

### 23.9 Конфигурация

```
DIGEST_WEEKDAY=1
DIGEST_HOUR=9
DIGEST_BATCH_SIZE=100
```

`DIGEST_WEEKDAY` — ISO-день 1..7, `DIGEST_HOUR` — час 0..23 **локального времени получателя**, не UTC: дайджест приходит утром понедельника тому, кто его читает, а не тому, кто настраивал сервер. Читается там же, где остальное окружение, — в `app/core/config.py` §11.1.

Перечисленные значения глобальные, а не пользовательские. Пользователю принадлежит один вопрос — нужен ли дайджест вообще §23.7, — и экрана выбора дня и часа S11 не заводит: три настройки ради сообщения раз в неделю дороже самого сообщения.

### 23.10 Ключи текстов (`bot/render/texts.py`)

`stats.by_category`, `stats.category_item`, `stats.category_none`, `stats.card`, `digest.title`, `digest.body`, `digest.category_item`, `settings.digest_on`, `settings.digest_off`, `settings.digest_saved`, `btn.digest_on`, `btn.digest_off`, `btn.stats_all`.

Кнопок у переключателя две, а не одна: она рисуется той стороной, которую нажатие включает, по правилу §21.6, и подписанная одним словом на оба состояния она не сказала бы, что сделает.

`stats.title` и `stats.body` есть с `v1` и не меняются.

`settings.title` из `v1` получает плейсхолдер `{digest}`: экран настроек — единственное место, где пользователь читает своё состояние, и переключатель, которого на нём не видно, выключить нельзя. Ключ и его имя не меняются, второго экрана настроек не заводится.

У каждого ключа обязательны обе локали и совпадающий набор плейсхолдеров — держится контрактным тестом.

Плейсхолдер `{digest}` обязывает `render_settings` §16.6 и `settings_kb` §16.4 знать состояние переключателя, поэтому обе правки едут в PR ядра вместе с ключом: строка, у которой некому подставить плейсхолдер, роняет экран настроек, а не откладывает его.

`render_stats(summary)` §9 расширяется разбивкой, и рядом с ним появляются `render_stats_card(summary, category, lang)` и `render_digest(summary, window, categories, lang)`. Это уже слайс §23.11: `bot/render/stats.py` — не общий файл §11.2, и ядро отдаёт ему ключи, а не рендер.

### 23.11 Модули слайса

Раскладка §3.1 дополняется четырьмя файлами, из которых клавиатуры §23.4 пишет тимлид, а остальные — слайс S11:

```
app/domain/digest.py           # недельный момент, окно, решение об отправке
app/bot/keyboards/stats.py     # разбивка и карточка категории
app/services/digest.py         # DigestService
app/worker/digest.py           # цикл digest.send
```

`app/domain/stats.py`, `app/services/stats.py`, `app/bot/render/stats.py` и `app/bot/handlers/stats.py` дополняются, новых модулей на их роли не заводится.

`UsersRepository` §3.1 дополняется двумя запросами: перечислить кандидатов на дайджест и отметить отправленный. `DeliveriesRepository.list_actions_for_user` возвращает категорию рядом с реакцией §23.1.6, потому что второй запрос на категорию каждой строки журнала — это `N+1` на месячной истории.

Цикл `digest.send` подключается в `app/worker/main.py` четвёртой задачей `TaskGroup` рядом с планировщиком, диспетчером и жнецом.

### 23.12 Границы слайса

Дайджест личный. Общей сводки по совместному напоминанию §22 сверх той, что видит сам получатель, S11 не заводит: §23.1.5 прямо запрещает складывать чужую дисциплину владельцу, и экран «как справляются остальные» противоречил бы этому запрету, а не дополнял его.

Экспорта, графиков и сравнения периодов между собой нет. `/stats` отвечает на два вопроса — «сколько дней подряд» и «какая доля», — и оба уже на экране.

Метрики самого воркера — размер очереди, лаг доставки, доля ошибок — это S12 §15, и к статистике пользователя они отношения не имеют.

---

## 24. Контракт слайса S12 (ops)

Добавлено в `v11`. Раздел append-only, как и весь файл: значения ниже не переименовываются.

Слайс закрывает дорожную карту §15 и не добавляет продукту ни одного экрана: всё, что он заводит, адресовано тому, кто держит бота работающим, а не тому, кто им пользуется.

### 24.1 Здоровье — это факт о цикле, а не о базе

Воркер §3 крутит циклы в `TaskGroup`, и `run_loop` ловит исключение, логирует и продолжает. Снаружи это неотличимо ни от здоровой работы, ни от зависшего цикла: процесс жив в обоих случаях. Healthcheck отвечает ровно на этот вопрос и ни на какой другой.

**Отметка ставится на каждой попытке цикла, успешной и упавшей.** База, моргнувшая на минуту, роняет каждый цикл, но петля при этом крутится, и перезапускать воркер незачем: он ничем не болен, а перезапуск в момент недоступности базы не лечит вообще ничего и складывается в цикл рестартов. Зависший цикл ловится тем же механизмом с другой стороны: отметка перестаёт двигаться, потому что попытка не завершилась.

Отсюда же следует, что `/healthz` не ходит в БД. Ошибки самих циклов видны в метриках §24.2 и в логах, а healthcheck остаётся дешёвым и не превращает доступность базы в условие жизни процесса.

Цикл считается устаревшим, когда с его последней отметки прошло больше

```
max(interval * HEALTH_STALE_FACTOR, HEALTH_STALE_FLOOR_SECONDS)
```

Пол нужен диспетчеру: его период `DISPATCH_INTERVAL_SECONDS` §11.1 равен десяти секундам, и тройка от него — тридцать секунд, меньше одного тика планировщика. Без пола нормальная пауза одного цикла выглядела бы отказом соседнего.

Эндпоинты воркера. Оба машинные, `T(...)` §9 к ним не применяется: получатель — `docker healthcheck` и скрейпер, а не человек.

| путь | ответ |
|---|---|
| `GET /healthz` | `200` и `{"status": "ok", "cycles": [...]}`; `503` и `{"status": "stale", ...}`, когда устарел хотя бы один цикл |
| `GET /metrics` | `200`, Prometheus text exposition |

```python
class HealthStatus(StrEnum):
    OK = "ok"
    STALE = "stale"
```

Enum append-only §4.1. Третьего состояния у healthcheck нет намеренно: ответ читает `docker healthcheck`, у которого исходов ровно два, и промежуточное «предупреждение» ему некуда деть.

Сервер поднимается только в процессе `worker`. У процесса `bot` есть свой признак жизни — он отвечает Telegram, — и второй порт ради того же факта только добавил бы способ их рассинхронизировать.

### 24.2 Метрики: три числа §15

Числа считаются чистыми функциями из снимка очереди, поэтому проверяются property-тестами, а не базой и часами, ровно по причине §20.3.

| метрика | определение |
|---|---|
| размер очереди | доставки в `pending` и `snoozed` §4.1 с `next_attempt_at <= now` |
| лаг доставки | `now` минус самый старый такой `next_attempt_at`; ноль на пустой очереди |
| доля ошибок | `failed / (failed + delivered)` внутри окна `METRICS_WINDOW_MINUTES` |

Размер очереди считается по **просроченным** доставкам, а не по всем незакрытым: напоминание, назначенное на завтра, лежит в очереди по замыслу, и складывать его с тем, что диспетчер не успел отправить, значит мерить не отставание, а популярность бота.

Доля ошибок на нулевом знаменателе равна нулю, а не единице, по причине §23.2.6: ничего не отправлялось, а не всё провалилось. `delivered` — доставки, чьё сообщение вышло (`sent`, `done`, `skipped`, `snoozed`), `failed` — `failed` и `blocked` §4.1. Доставки, ещё стоящие в очереди, не попадают ни в числитель, ни в знаменатель: они о транспорте пока ничего не говорят.

Окно берётся по `occurrences.fire_at`, а не по `deliveries.updated_at`. `updated_at` §4.2 пишет `now()` самой базы, а каждый прочий момент в продукте приходит из `Clock` §8; смешивать двое часов ради метрики нельзя, и `fire_at` отвечает на тот же вопрос словами домена: какая доля дел, у которых наступил срок за последние минуты, не доехала.

`/metrics` отдаёт последний отчёт, опубликованный циклом §24.3, и сам в БД не ходит. Скрейп раз в пятнадцать секунд не должен уметь нагрузить ту же очередь, за которой наблюдает, а возраст отчёта отдаётся отдельной метрикой, так что залипший цикл виден в самой экспозиции.

### 24.3 `ops.monitor` — пятый цикл воркера

```python
class JobId(StrEnum):
    OPS_MONITOR = "ops.monitor"
```

Enum append-only §4.1. Джоб описан как контракт и тестируется как джоб §7.

- Период: `PLANNER_INTERVAL_SECONDS`. Отдельной переменной на то же число не заводится по причине §20.8.
- Действие: снять снимок очереди одним запросом, собрать отчёт §24.2, опубликовать его для `/metrics`, решить про алерт.
- Алерт уходит админам из `ADMIN_USER_IDS` §11.1 через существующий `BotGateway` §8. Второго транспорта слайс не заводит: канал до человека у продукта уже есть, а почта или вебхук потребовали бы своей конфигурации, своего фейка и своего пути ошибки ради того же одного сообщения.
- Адресат — `chat_id`, равный tg-идентификатору админа: приватный чат с ботом у него тот же самый §4.2. Язык — `DEFAULT_LANGUAGE` §11.1. Строки в `users` у админа может не быть вовсе, и запрос за ней ради языка операторского сообщения не окупается.
- Порог: `ALERT_LAG_MINUTES` §24.6, по умолчанию пять минут §15. Сравнение строгое: лаг ровно в пять минут — ещё не алерт, как и `expires_at == now` §20.3.2 — ещё не просрочка.

**Идемпотентность держится на переходе, а не на тике.** Сообщение уходит на фронте `clear -> firing`, восстановление — на фронте `firing -> clear`. Два прогона подряд в одном состоянии шлют ровно одно сообщение, как требует §10.2. Алерт, повторяемый каждую минуту, — это не наблюдение, а способ научить оператора его игнорировать.

Состояние живёт в памяти процесса, а не в БД: оно принадлежит наблюдателю, а не продукту. Рестарт воркера сбрасывает его в `clear`, и первый же тик поднимает алерт заново, если лаг никуда не делся. Потерять предупреждение таким сбросом нельзя, а лишняя строка в схеме ради него стоила бы миграции.

- `ADMIN_USER_IDS` пуст — цикл всё равно меряет, публикует отчёт и логирует. Не отправляет ничего и ошибкой это не считает: на тестовом стенде админов может не быть.
- Сбой отправки алерта не роняет цикл и не защёлкивает состояние: переход фиксируется только после успешной отправки, поэтому `TelegramRetryAfter` §7.2 просто откладывает предупреждение до следующего тика. Ретраев внутри тика нет: тик через минуту, и второй заход внутри него ничего не ускоряет.
- `TelegramForbiddenError` на админе снимает его с рассылки до конца жизни процесса, а не помечает `users.is_blocked`: строки пользователя у него может не быть, а флаг §4.2 принадлежит доставке напоминаний, не алертам.

### 24.4 Бэкап

`scripts/backup.sh`: `pg_dump -Fc` в `BACKUP_DIR`, имя `reminder-YYYYmmddTHHMMSSZ.dump`, ретенция `BACKUP_KEEP_DAYS`, ненулевой код возврата на любой ошибке. Формат custom, а не текстовый: он сжат, и `pg_restore` умеет разбирать его по объектам.

Скрипт запускается кроном хоста и обёрнут целями `make backup` и `make restore f=<файл>`. Пятого постоянно работающего контейнера ради задачи, которая просыпается раз в сутки, слайс не заводит.

Ретенция удаляет файлы старше `BACKUP_KEEP_DAYS` **после** успешного дампа и только в `BACKUP_DIR`. Порядок важен: чистка перед дампом на упавшем `pg_dump` оставила бы каталог, в котором нет ни свежего бэкапа, ни старых.

`BACKUP_*` живут в `.env.example`, но не в `Settings` §11.1: их читает shell, а запрет на `os.environ` относится к Python-коду. Второго места, читающего окружение из Python, не появляется.

### 24.5 Ротация логов

Драйвер `json-file` с `max-size` и `max-file` на каждом сервисе `docker/compose.yml`. Внутри контейнера не ротируется ничего: приложение пишет структурный поток в stdout §3.1, файлом владеет докер, и второй механизм на ту же работу разошёлся бы с первым.

Воркер получает `healthcheck`, ходящий в `/healthz` §24.1 изнутри контейнера, и `restart: unless-stopped`: эндпоинт без того, кто его спрашивает, — это метрика, а не healthcheck.

### 24.6 Конфигурация

```
HEALTH_HOST=0.0.0.0
HEALTH_PORT=8080
ALERT_LAG_MINUTES=5
METRICS_WINDOW_MINUTES=15
BACKUP_DIR=/var/backups/reminder
BACKUP_KEEP_DAYS=14
```

Порт наружу не публикуется: и `docker healthcheck`, и скрейпер ходят изнутри сети compose. Открытый в интернет `/metrics` рассказывал бы размер очереди всякому, кто спросит.

`HEALTH_HOST` по умолчанию слушает все интерфейсы контейнера, потому что healthcheck докера приходит не с петли хоста. В локальном запуске вне контейнера значение сужается до `127.0.0.1`.

### 24.7 Модули слайса

Раскладка §3.1 дополняется четырьмя файлами, которые пишет слайс S12:

```
app/domain/ops.py        # лаг, доля ошибок, устаревание цикла, переход алерта
app/services/ops.py      # OpsService: снимок -> отчёт -> алерт
app/worker/health.py     # отметки циклов, HTTP-эндпоинты, экспозиция метрик
app/worker/ops.py        # цикл ops.monitor
```

`DeliveriesRepository` §3.1 дополняется одним запросом: снимок очереди целиком. Три отдельных запроса за тремя числами дали бы три разных момента времени в одном отчёте.

`app/worker/main.py` подключает пятую задачу `TaskGroup` рядом с планировщиком, диспетчером, жнецом и дайджестом, поднимает HTTP-сервер до неё и гасит его после.

Публичный API домена:

```python
@dataclass(frozen=True, slots=True)
class QueueSnapshot:
    due_deliveries: int
    oldest_due_at: datetime | None
    delivered: int
    failed: int

@dataclass(frozen=True, slots=True)
class OpsReport:
    taken_at: datetime
    queue_size: int
    lag: timedelta
    error_ratio: float

@dataclass(frozen=True, slots=True)
class CycleBeat:
    job: JobId
    interval_seconds: float
    last_tick_at: datetime
    failures: int = 0

@dataclass(frozen=True, slots=True)
class AlertDecision:
    state: AlertState
    notify: AlertKind | None

def queue_lag(snapshot: QueueSnapshot, now: datetime) -> timedelta
def error_ratio(snapshot: QueueSnapshot) -> float
def build_report(snapshot: QueueSnapshot, now: datetime) -> OpsReport
def stale_after(beat: CycleBeat) -> timedelta
def is_stale(beat: CycleBeat, now: datetime) -> bool
def health_status(beats: Iterable[CycleBeat], now: datetime) -> HealthStatus
def decide_alert(state: AlertState, lag: timedelta, threshold: timedelta) -> AlertDecision
```

`AlertState` — `StrEnum` из `clear | firing`, `AlertKind` — из `raised | cleared`. Состояние и уведомление разведены: состояние держится между тиками, уведомление принадлежит одному тику и пусто на всех тиках, кроме фронта.

Правила, обязательные к соблюдению:

1. лаг неотрицателен всегда: очередь, где `next_attempt_at` в будущем, отстаёт на ноль, а не на отрицательную величину;
2. `error_ratio` лежит в `[0, 1]` и равен нулю на нулевом знаменателе §24.2;
3. `is_stale` монотонна по времени: цикл, признанный устаревшим, не оживает от того, что часы пошли дальше;
4. `health_status` возвращает `STALE`, когда устарел хотя бы один цикл, и `OK` на пустом наборе: воркер, который ещё не завёл ни одного цикла, не болен, он не начался;
5. `decide_alert` уведомляет только на фронте: два вызова подряд с тем же `lag` дают уведомление максимум в первом;
6. функции чистые: ни часов, ни IO, ни импортов вне stdlib и `app/domain`.

### 24.8 Ключи текстов (`bot/render/texts.py`)

`ops.alert_lag`, `ops.alert_cleared`.

У каждого ключа обязательны обе локали и совпадающий набор плейсхолдеров — держится контрактным тестом. Оба ключа несут `{lag}`, `{queue}` и `{errors}`: сообщение о восстановлении, не показывающее чисел, требует от оператора верить на слово ровно там, где он и полез проверять.

Ключи лежат в `texts.py`, хотя адресат у них не пользователь: §12 не делает исключений, а второе место для строк, отправляемых в Telegram, разошлось бы с первым.

### 24.9 Границы слайса

Своего Prometheus, Grafana и alertmanager S12 не поднимает. Экспозиция отдаётся в стандартном формате, а кто её собирает и хранит, решает хост: тянуть в compose стек наблюдения ради трёх чисел дороже самих чисел.

Метрик на пользователя нет. Пользовательские числа — это §23, они считаются по журналу и принадлежат получателю; складывать их с метриками транспорта нельзя, потому что первые говорят о человеке, а вторые о доставке.

Трейсинга, профилирования и `/readyz` слайс не заводит. Готовность у воркера совпадает с жизнью: он не принимает входящих запросов, и разводить два эндпоинта на один факт незачем.

---

## 25. Контракт справки и меню команд

Добавлено в `v12`. Раздел append-only, как и весь файл: значения ниже не переименовываются.

Раздел не принадлежит ни одному слайсу дорожной карты §15: она закрыта целиком. Он закрывает то, чего ни один слайс не закрывал, — первую минуту нового пользователя. Продукт из восьми команд, ни одна из которых нигде не перечислена, для человека, открывшего бота впервые, неотличим от сломанного.

### 25.1 Один список, два потребителя

Меню команд Telegram и таблица команд в `/help` — это один факт, показанный дважды. Разъехавшись, они врут в обе стороны: меню предлагает то, чего нет, либо справка умалчивает о том, что есть. Поэтому список команд живёт в одном месте, `app/bot/commands.py`, и оба экрана собираются из него.

Сцепление держит контрактный тест, а не память: у каждой команды меню есть зарегистрированный в диспетчере хендлер, и каждый хендлер команды попадает в меню. Тест ходит по реальному диспетчеру, собранному `build_dispatcher`, а не по копии списка.

Исключение из второго правила ровно одно, `/start`, и оно объявляется именованной константой, а не забывается:

```python
MENU_EXEMPT_COMMANDS: Final[frozenset[str]] = frozenset({"start"})
```

У Telegram своя кнопка Start, и дублировать её пунктом меню незачем. Исключение названо в коде, поэтому тест его проверяет, а не обходит: команда, тихо выпавшая из меню, ничем не отличалась бы от команды, тихо выпавшей по забывчивости.

### 25.2 Меню едет через протокол

§8 требует, чтобы всё внешнее сидело за протоколом и работало против фейка с первого дня. Меню команд — сетевой вызов Telegram, значит оно не исключение:

```python
@dataclass(frozen=True, slots=True)
class BotCommandSpec:
    command: str          # без ведущего слэша
    description: str

class BotGateway(Protocol):
    async def set_commands(self, commands: Sequence[BotCommandSpec], lang: str) -> None: ...
```

`command` едет без слэша, как его принимает Telegram. Слэш дорисовывает рендер справки, и хранить его в списке значило бы разложить одно значение в двух формах.

`FakeBotGateway` записывает вызовы в `commands: dict[str, tuple[BotCommandSpec, ...]]` по локали и **валидирует контракт** ровно так же, как `validate_outgoing` валидирует сообщение:

```python
COMMAND_PATTERN: Final = r"^[a-z0-9_]{1,32}$"
COMMAND_DESCRIPTION_MAX_LENGTH: Final = 256
COMMANDS_MAX: Final = 100
```

Нарушение — `ContractViolation`, тест падает. Без этого меню осталось бы единственной частью бота, которую в `USE_FAKE_BOT=true` §11.1 нечем проверить, и первым, что сломалось бы у живого пользователя.

Локаль передаётся отдельным аргументом, а не зашивается в список: описания лежат в `texts.py` в обеих локалях §9, и меню публикуется по одному вызову на каждую из `SUPPORTED_LANGS`.

### 25.3 Меню не мешает боту стартовать

Публикация меню — сетевой вызов в момент старта процесса. Если Telegram его отклонил, процесс `bot` всё равно уходит в polling, а отказ пишется в лог уровня error.

Бот, не поднимающийся из-за неудавшегося обновления подписей к командам, хуже бота с устаревшим меню: во втором случае не работает подсказка, в первом не работает продукт. Это то же правило, по которому §23.5 не роняет пачку дайджеста из-за одного получателя.

### 25.4 Молчание — не ответ

Ни один хендлер сообщений не зарегистрирован без фильтра, поэтому текст, не являющийся ни командой, ни ответом мастеру, не получает ничего. В мессенджере это читается как поломка, а не как «я тебя не понял»: пользователь не видит разницы между ботом, который его проигнорировал, и ботом, который упал.

Перехватчик отвечает ключом `help.unknown` и включается **последним роутером**, перед `errors.router`. Это и есть условие его безопасности, а не стилистика: каждый текстовый хендлер продукта отфильтрован состоянием FSM и лежит в роутере, зарегистрированном раньше, поэтому перехватчик физически не может съесть ввод мастера. Порядок держится тестом: текст внутри `ReminderWizard.title` обязан уходить мастеру.

Обратная сторона того же правила: пользователь в состоянии, которое ждёт только нажатия кнопки, на текст тоже получает ответ, а не тишину.

### 25.5 Онбординг заканчивается справкой

`_finish_onboarding` §16 показывал экран настроек. Человек, только что назвавший таймзону, получал список настроек вместо ответа на вопрос «а дальше что»: настройки он уже прошёл, а продукта ещё не видел.

После сохранения таймзоны показывается справка. Экран приглашения §22.5 по-прежнему выигрывает у обоих: пришедший по ссылке пришёл не за справкой, а за конкретным напоминанием, и подменять ответ на его вопрос оглавлением нельзя.

### 25.6 Ключи текстов (`bot/render/texts.py`)

`help.screen`, `help.unknown`, `cmd.new`, `cmd.list`, `cmd.today`, `cmd.categories`, `cmd.stats`, `cmd.shared`, `cmd.settings`, `cmd.help`.

У каждого ключа обязательны обе локали и совпадающий набор плейсхолдеров — держится контрактным тестом.

`help.screen` плейсхолдеров не несёт вовсе, и таблица команд подставляется не форматированием, а склейкой из `cmd.*`. Иначе добавление девятой команды правило бы строку в двух местах, что §25.1 и запрещает.

Описания `cmd.*` служат обоим экранам: и пунктом меню Telegram, и строкой таблицы в справке. Второго набора описаний на то же самое не заводится.

### 25.7 Модули

Раскладка §3.1 дополняется тремя файлами:

```
app/bot/commands.py        # порядок команд и ключи их описаний
app/bot/render/help.py     # сборка экрана справки
app/bot/handlers/help.py   # /help и ответ на непонятный текст
```

`app/bot/commands.py` держит только список и `menu_for(lang)`. Рендера в нём нет: список — это контракт, а его отображение принадлежит `bot/render/` §3.1.

### 25.8 Границы

Раздел не заводит ни экрана справки с разделами на кнопках, ни новой CallbackData-фабрики. Справка — один текст: продукт из восьми команд объясняется быстрее, чем читается меню разделов о нём.

Онбординг-туториала с шагами тоже нет. Мастер `/new` §18 уже ведёт пользователя по шагам, и второй пошаговый сценарий поверх него объяснял бы первый вместо того, чтобы дать им воспользоваться.

---

## 26. Контракт главного меню

Добавлено в `v13`. Раздел append-only, как и весь файл: значения ниже не переименовываются.

§9 обещает reply-клавиатуру главному меню и на этом останавливается: ни один слайс её не собрал. Продукт остался управляемым только слэш-командой, то есть требующим помнить восемь слов, тогда как §25 уже признал, что первую минуту пользователя нельзя оставлять на память. Меню команд Telegram спрятано за кнопкой и показывает список, а не действие; постоянная клавиатура показывает действие.

### 26.1 Третий потребитель того же списка

§25.1 назвал меню команд и таблицу в `/help` одним фактом, показанным дважды. Клавиатура — третий его показ, и она собирается из того же `app/bot/commands.py`. Разъехавшись, она врёт ровно так же: кнопка ведёт в никуда либо продукт скрывает от пользователя половину себя.

Изъятий у клавиатуры нет. `MENU_EXEMPT_COMMANDS` §25.1 касается только меню Telegram, у которого есть своя кнопка Start; на клавиатуре дублировать нечего, потому что `/start` не действие продукта, а первый контакт с ним. Все восемь команд §25.1 получают по кнопке, по две в ряд, в том же порядке.

Сцепление держит контрактный тест, а не память: у каждой кнопки есть команда, зарегистрированная в реальном диспетчере, и у каждой команды меню есть кнопка. Тест ходит по диспетчеру, собранному `build_dispatcher`, тем же способом, что и §25.1.

### 26.2 Подписи кнопок — свои ключи

Описания `cmd.*` §25.6 на кнопку не годятся: строка меню широкая, кнопка узкая, и «Таймзона, язык, тихие часы» на ней не помещается. Поэтому у клавиатуры свой набор ключей `btn.menu_*`, короткий.

Второго набора *описаний* при этом не заводится, и §25.6 не нарушается: у ключей разные роли. `cmd.*` объясняет, что команда делает, и живёт в меню и в справке. `btn.menu_*` называет экран одним-двумя словами и живёт на кнопке. Связывает их не текст, а имя команды, и связь проверяет тест §26.1.

Подписи — обычный текст без эмодзи, как и остальные шестьдесят строк `btn.*`.

### 26.3 Подпись сопоставляется по всем локалям

Reply-клавиатура рисуется в чате один раз и живёт там, пока её не заменят. Пользователь, сменивший язык §16, смотрит на клавиатуру, нарисованную прежней локалью, и нажимает подпись, которой в его нынешнем языке нет. Значит, сопоставление идёт по объединению `SUPPORTED_LANGS`, а не по языку пользователя:

```python
def main_menu_labels() -> dict[str, str]    # подпись -> имя команды, по всем локалям
```

Отсюда инвариант, который держит контрактный тест: подписи уникальны в объединении локалей. Совпавшие подписи двух команд означали бы кнопку, ведущую куда придётся.

Клавиатура при этом перерисовывается при смене языка, потому что читать её пользователь должен на своём языке. Перерисовка — это новое сообщение: `reply_markup` принадлежит сообщению, и правка старого его не меняет.

### 26.4 Нажатие выигрывает у свободного текста

Нажатая кнопка приходит обычным текстовым сообщением, неотличимым от ответа мастеру. Поэтому роутер меню регистрируется **первым**, и это условие корректности, а не предпочтение: навигация обязана выигрывать у свободного текста, иначе мастер съест кнопку и назовёт напоминание «Статистика».

Это зеркало §25.4: перехватчик непонятного текста стоит последним, потому что он не должен выигрывать ни у кого; роутер меню стоит первым, потому что он должен выигрывать у всех. Оба держат один инвариант с разных концов, и оба проверяются порядком роутеров в тесте.

Цена известна и принимается: напоминание, названное ровно подписью кнопки, завести с клавиатуры нельзя. Восемь строк, отнятых у названий, дешевле кнопки, которая иногда не срабатывает.

### 26.5 Навигация снимает мастера

Набранная команда до `v13` не выигрывала у мастера вовсе: текстовые шаги FSM фильтровались только состоянием, и `/list` на шаге «название» становилась названием напоминания. С клавиатурой это расхождение стало видимым — кнопка уводит на экран, а та же команда словом остаётся текстом, — поэтому правило одно на обе формы:

1. текстовые шаги FSM не принимают команды за текст. Фильтр `NOT_A_COMMAND` собран один раз и перечисляет все команды §25.1 вместе с изъятыми §25.1;
2. открытие экрана снимает состояние FSM. Это касается каждой из восьми команд и каждой кнопки: пользователь, ушедший из мастера, не должен обнаружить, что его следующая фраза стала названием брошенного напоминания;
3. кнопка не повторяет тело команды, а вызывает её хендлер. Второй экземпляр той же логики разошёлся бы с первым, как разошлись бы меню и справка §25.1.

### 26.6 Клавиатура (`bot/keyboards/menu.py`)

| примитив | контракт |
|---|---|
| `main_menu_kb(lang)` | восемь кнопок §26.1 по две в ряд, `resize_keyboard`, `is_persistent` |

`is_persistent` обязателен: клавиатура, которую пользователь свернул однажды, не должна исчезать навсегда. `one_time_keyboard` запрещён по той же причине с другой стороны: меню, прячущееся после первого нажатия, перестаёт быть постоянным ровно тогда, когда им начали пользоваться.

Единственная reply-клавиатура продукта §9. Все остальные экраны остаются инлайновыми, и `OutgoingMessage` §8 по-прежнему несёт только `InlineKeyboardMarkup`: клавиатура принадлежит процессу `bot`, а воркер шлёт напоминания с кнопками реакции и меню не рисует.

Клавиатура прикрепляется там, где сообщение не несёт инлайновой: приветствие вернувшегося §16, конец онбординга §25.5, `/help`, ответ на непонятный текст §25.4 и сообщение о смене языка §26.3. Одно сообщение несёт одну `reply_markup`, и выбирать между инлайновым экраном и меню в одном сообщении нельзя.

### 26.7 Ключи текстов (`bot/render/texts.py`)

`btn.menu_new`, `btn.menu_list`, `btn.menu_today`, `btn.menu_categories`, `btn.menu_stats`, `btn.menu_shared`, `btn.menu_settings`, `btn.menu_help`.

У каждого ключа обязательны обе локали и совпадающий набор плейсхолдеров — держится контрактным тестом. Плейсхолдеров у подписей нет вовсе: подпись кнопки статична, а `main_menu_labels` §26.3 строит индекс сравнением строк, и подставленное в подпись значение сделало бы кнопку неузнаваемой.

### 26.8 Модули

Раскладка §3.1 дополняется тремя файлами:

```
app/bot/filters.py            # NOT_A_COMMAND, собранный один раз
app/bot/keyboards/menu.py     # постоянная клавиатура главного меню
app/bot/handlers/menu.py      # нажатие кнопки -> хендлер команды
```

`app/bot/commands.py` §25.7 дополняется порядком кнопок, индексом подписей и полным списком имён команд. Рендера в нём по-прежнему нет.

### 26.9 Границы

Раздел не заводит ни второго уровня клавиатуры, ни кнопки «назад» на ней. Reply-клавиатура — оглавление продукта, а не навигация внутри экрана: внутри экрана навигацию несут инлайновые кнопки и CallbackData-фабрики §6.

Выключателя клавиатуры нет. Постоянное меню — это и есть ответ на вопрос §25, с которого начался предыдущий раздел, и настройка, прячущая ответ, вернула бы вопрос.
