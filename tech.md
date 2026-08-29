# tech.md — ядро проекта Reminder Bot

**Версия ядра: v4**

Changelog:
- `v1` — первичная фиксация: стек, структура, схема БД, контракты расписаний и воркеров, протоколы гейтвеев, стратегия тестов, дорожная карта.
- `v2` — §0 состав команды и совмещение ролей; §12.2 авторство коммитов и PR (git identity, запрет посторонних трейлеров).
- `v3` — §16 контракт слайса S1: enum `Language`, список `POPULAR_TIMEZONES`, CallbackData-фабрика `SetCb` (префикс `s`), публичные `parse_hhmm`/`format_hhmm`, клавиатуры настроек, ключи текстов, три новых модуля слайса.
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
