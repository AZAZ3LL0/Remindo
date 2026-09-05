# Reminder Bot

Телеграм-бот персональных напоминаний.

Источник истины по архитектуре, контрактам и процессу — [tech.md](tech.md).
Правила работы сессии — [CLAUDE.md](CLAUDE.md).

## Быстрый старт

```bash
cp .env.example .env          # USE_FAKE_BOT=true работает без реального токена
make up                       # db + bot + worker
make migrate                  # alembic upgrade head
make seed                     # системные категории и демо-данные
```

## Проверки

```bash
make lint && make typecheck && make test
```

Все команды выполняются внутри контейнера `app` (Python 3.12), поэтому
локальный интерпретатор и виртуальное окружение не нужны.

## Процессы

| процесс | точка входа | назначение |
|---|---|---|
| `bot` | `python -m app.bot.main` | принимает апдейты, пишет в БД, ничего не рассылает |
| `worker` | `python -m app.worker.main` | planner, dispatcher, reaper, digest, ops |
| `migrator` | `alembic upgrade head` | one-shot шаг деплоя |

## Тесты

```
make test        # весь набор с гейтом покрытия 85% по app/domain и app/services
make test-unit   # unit и contract, без БД
make gate        # полный гейт на эфемерном стеке, как в CI
```

`tests/unit` и `tests/contract` не ходят в БД. `tests/integration` и `tests/e2e`
поднимают схему через `alembic upgrade head` в базе `TEST_DATABASE_URL`.

## Ops

Воркер отдаёт два машинных эндпоинта на `HEALTH_PORT` (наружу порт не
публикуется, оба вопроса задаются изнутри сети compose):

```bash
make health
```

```bash
make metrics
```

`/healthz` отвечает `200`, пока каждый цикл воркера отмечается вовремя, и
`503`, когда хотя бы один перестал. В базу он не ходит: моргнувшая база роняет
циклы, но не воркер, и перезапускать его в этот момент бессмысленно.

`/metrics` отдаёт Prometheus text exposition: размер очереди, лаг доставки,
доля ошибок и возраст последнего отчёта. Отчёт снимает цикл `ops.monitor`, сам
эндпоинт в БД не ходит.

Лаг больше `ALERT_LAG_MINUTES` уводит алерт в Telegram админам из
`ADMIN_USER_IDS`. Сообщение уходит один раз на переходе в проблему и один раз
на возврате в норму, а не каждую минуту.

Логи ротирует докер: `json-file`, 10 МБ на файл, пять файлов на сервис.

### Бэкап

```bash
make backup
```

Дамп в формате custom ложится в `backups/` (в контейнере `db` — `/backups`),
файлы старше `BACKUP_KEEP_DAYS` удаляются после успешного дампа. На VPS та же
строка ставится в крон хоста:

```
17 3 * * * cd /srv/reminder && docker compose -f docker/compose.yml exec -T -e BACKUP_DIR=/backups db /srv/scripts/backup.sh
```

Восстановление из файла:

```bash
make restore f=reminder-20260905T031700Z.dump
```

## Деплой

Автодеплой из `main` (`.github/workflows/deploy.yml`) по SSH. Нужны секреты
окружения `staging`: `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`,
`DEPLOY_PATH`. Пока `DEPLOY_HOST` не задан, шаг пропускается и workflow зелёный.
`.env` живёт на хосте и в репозиторий не попадает.
