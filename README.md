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
| `worker` | `python -m app.worker.main` | planner, dispatcher, reaper |
| `migrator` | `alembic upgrade head` | one-shot шаг деплоя |

## Тесты

```
make test        # весь набор с гейтом покрытия 85% по app/domain и app/services
make test-unit   # unit и contract, без БД
make gate        # полный гейт на эфемерном стеке, как в CI
```

`tests/unit` и `tests/contract` не ходят в БД. `tests/integration` и `tests/e2e`
поднимают схему через `alembic upgrade head` в базе `TEST_DATABASE_URL`.

## Деплой

Автодеплой из `main` (`.github/workflows/deploy.yml`) по SSH. Нужны секреты
окружения `staging`: `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`,
`DEPLOY_PATH`. Пока `DEPLOY_HOST` не задан, шаг пропускается и workflow зелёный.
`.env` живёт на хосте и в репозиторий не попадает.
