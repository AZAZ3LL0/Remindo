# Деплой на VPS

Прод-стек — `docker/compose.prod.yml` ([tech.md §27](../tech.md)), автодеплой из
`main` — `.github/workflows/deploy.yml` (§28). Ниже полный путь от чистого
сервера до работающего бота.

## 0. Что нужно до начала

| что | откуда |
|---|---|
| `BOT_TOKEN` | BotFather |
| `BOT_USERNAME` | имя бота без `@`; из него собираются ссылки-приглашения (§22.9) |
| `ADMIN_USER_IDS` | ваш tg-id: на него уходят алерты о лаге доставки (§24.3) |
| доступ по SSH | пользователь с правом запускать `docker` |

Требования к хосту: Debian 12 или Ubuntu 22.04+, 2 ГБ RAM, 2 ГБ свободного
диска, `docker` с плагином `compose` v2.

## 1. Проверка сервера

```bash
. /etc/os-release; echo "$PRETTY_NAME $(uname -r)"; nproc; free -m; df -h /
docker --version; docker compose version
docker ps --format '{{.Names}}\t{{.Ports}}'
ss -tulpnH | awk '{print $5}' | sort -u
docker network inspect $(docker network ls -q) --format '{{.Name}} {{range .IPAM.Config}}{{.Subnet}}{{end}}'
```

Стек не публикует наружу ни одного порта: Postgres и `HEALTH_PORT` живут внутри
сети compose (§24.6, §27.3). Поэтому занятые хостом порты значения не имеют, и
проверять надо другое — свободную память и свободные подсети докера.

### Соседство с Marzban

Панель занимает 80, 443, порт дашборда и порты xray, держит свою базу и своё
имя проекта. Наш стек называется `reminder`, том `pgdata`, сеть своя, наружу
ничего не публикуется, поэтому пересечения нет ни по портам, ни по контейнерам,
ни по данным.

Остаются два общих ресурса:

**Память.** Postgres 16 и два Python-процесса — 250–400 МБ в покое. Marzban с
xray — ещё 200–400 МБ. На 2 ГБ оба стека живут спокойно. На 1 ГБ нужен swap,
иначе OOM-killer выберет Postgres как самый крупный процесс:

```bash
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

**Подсети докера.** Каждый стек занимает свою `/16` из пула `172.16.0.0/12`,
и их там 16. Если `docker network inspect` показывает, что пул выбран, задайте
пул в `/etc/docker/daemon.json` и перезапустите докер:

```json
{"default-address-pools": [{"base": "10.201.0.0/16", "size": 24}]}
```

CPU наш стек не потребляет: planner просыпается раз в минуту, dispatcher — раз
в десять секунд, обе задачи заканчиваются за миллисекунды на пустой очереди.

## 2. Docker, если его нет

```bash
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker
docker compose version
```

Установщик не трогает уже стоящий докер и не задевает контейнеры Marzban.

## 3. Клон и `.env`

```bash
install -d /srv && cd /srv
git clone https://github.com/AZAZ3LL0/Remindo.git reminder
cd reminder
cp .env.example .env
```

Репозиторий приватный, поэтому клон идёт по ключу деплоя либо по HTTPS с
токеном. Ключ — read-only deploy key репозитория, а не ваш личный.

Правки в `.env`, обязательные для прода:

```
ENV=prod
BOT_TOKEN=<токен от BotFather>
BOT_USERNAME=<имя бота без @>
USE_FAKE_BOT=false
ADMIN_USER_IDS=<ваш tg-id>
DEFAULT_TIMEZONE=Europe/Moscow
```

`DATABASE_URL` не трогайте: адрес `db:5432` разрешается внутри сети compose.
`HEALTH_*`, `PLANNER_*`, `DISPATCH_*` и `DIGEST_*` работают на умолчаниях.

`.env` принадлежит хосту, в репозиторий не попадает и в образ не входит
(§27.1, §28.3). Права на него — `chmod 600`.

## 4. Первый запуск

```bash
cd /srv/reminder
make prod-build
make prod-migrate                 # alembic upgrade head одноразовым контейнером
make prod-up
docker compose -f docker/compose.prod.yml ps
```

Системные категории заводятся один раз:

```bash
docker compose -f docker/compose.prod.yml run --rm migrator python -m scripts.seed
```

Скрипт идемпотентен, но демо-данные ему тоже принадлежат: на боевой базе
запускайте его только на пустой схеме.

Проверка, что стек жив:

```bash
docker compose -f docker/compose.prod.yml exec -T worker curl -fsS http://127.0.0.1:8080/healthz
docker compose -f docker/compose.prod.yml logs --tail 30 bot worker
```

`/healthz` отвечает `200`, пока каждый из пяти циклов воркера отмечается
вовремя, и `503`, когда хотя бы один перестал (§24.1). После этого напишите
боту `/start`.

## 5. Автодеплой

Секреты окружения `staging` в настройках репозитория:

| секрет | значение |
|---|---|
| `DEPLOY_HOST` | адрес сервера |
| `DEPLOY_USER` | пользователь с доступом к `docker` |
| `DEPLOY_SSH_KEY` | приватный ключ этого пользователя целиком |
| `DEPLOY_PATH` | `/srv/reminder` |

Пока `DEPLOY_HOST` не задан, шаг деплоя пропускается и workflow остаётся
зелёным. После — каждый пуш в `main` пересобирает образ, прогоняет миграции
одноразовым контейнером, поднимает `bot` и `worker` и опрашивает `/healthz`.
Деплой падает, если стек не поднялся, и печатает `ps` и последние строки логов
(§28.2).

Публичный ключ кладётся в `~/.ssh/authorized_keys` пользователя деплоя:

```bash
ssh-keygen -t ed25519 -C deploy -f ./deploy_key -N ''
cat deploy_key.pub >> ~/.ssh/authorized_keys      # на сервере
cat deploy_key                                     # в секрет DEPLOY_SSH_KEY
```

## 6. Бэкап

Дамп снимает контейнер `db`, которому принадлежит `pg_dump` (§24.4). В крон
хоста:

```
17 3 * * * cd /srv/reminder && docker compose -f docker/compose.prod.yml exec -T -e BACKUP_DIR=/backups db /srv/scripts/backup.sh
```

Файлы ложатся в `backups/` рядом с клоном, старше `BACKUP_KEEP_DAYS` удаляются
после успешного дампа. Восстановление:

```bash
docker compose -f docker/compose.prod.yml exec -T db pg_restore --clean --if-exists --no-owner \
  --dbname postgresql://app:app@localhost:5432/reminder /backups/<файл>.dump
```

## 7. Что ломается чаще всего

| симптом | причина |
|---|---|
| бот молчит, в логе `Unauthorized` | `BOT_TOKEN` не тот или остался `USE_FAKE_BOT=true` |
| бот отвечает, напоминания не приходят | воркер лежит: `logs worker`, затем `/healthz` |
| ссылки-приглашения ведут не туда | `BOT_USERNAME` не совпадает с реальным именем бота (§28.3) |
| апдейты приходят через раз | на одном токене два поллинга: рядом поднят dev-стек (§27.4) |
| `/healthz` отдаёт `503` | цикл перестал отмечаться; причина в логе воркера |
| Postgres убит без следа в своих логах | нет swap на 1 ГБ RAM: `dmesg | grep -i oom` |
