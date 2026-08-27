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
