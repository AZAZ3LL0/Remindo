Core change for **S12. Ops** (`tech.md` §15). Appends §24 and bumps the core to **v11**.

No slice code here. The last roadmap item needs a job id, a health enum, four settings, two text keys and a pinned dependency, and every one of those is a shared file (§11.2) that a slice does not touch.

## §24, and the three decisions in it

**Health is a fact about the cycle, not about the database.** `run_loop` already catches, logs and continues, so from outside a healthy worker and a hung one look identical. The heartbeat is stamped on *every attempt*, failed ones included: a database that blinks for a minute knocks over all five cycles while the loop keeps turning, and restarting the worker at exactly that moment cures nothing and compounds into a restart loop. A genuinely hung cycle is still caught, from the other side — its attempt never finishes, so its mark stops moving. That is also why `/healthz` does not query the database.

A cycle is stale after `max(interval * HEALTH_STALE_FACTOR, HEALTH_STALE_FLOOR_SECONDS)`. The floor exists for the dispatcher: its period is ten seconds, and three of those is less than one planner tick, so a normal pause in one cycle would read as a failure in its neighbour.

**The error window is measured on `occurrences.fire_at`, not on `deliveries.updated_at`.** `updated_at` is written by the database's own `now()`, and every other moment in the product comes from `Clock` (§8). Mixing two clocks for the sake of a metric is not worth it, and `fire_at` answers the same question in the domain's own words: of the things that came due in the last few minutes, what share did not get out.

**The alert fires on the edge, not on the tick.** One message when the lag crosses `ALERT_LAG_MINUTES`, one when it comes back, nothing in between. An alert repeated every minute is not observation, it is a way to teach an operator to ignore it. The state lives in process memory rather than in a row: it belongs to the observer, not to the product, and a restart that resets it to `clear` costs one re-alert on the next tick instead of a migration.

## What lands

| file | change |
|---|---|
| `tech.md` | §24, version `v11`, changelog line |
| `app/domain/contracts.py` | `JobId.OPS_MONITOR`, `HealthStatus` (`ok` / `stale`) |
| `app/core/config.py`, `.env.example` | `HEALTH_HOST`, `HEALTH_PORT`, `ALERT_LAG_MINUTES`, `METRICS_WINDOW_MINUTES`, plus `BACKUP_*` for the shell only |
| `app/bot/render/texts.py` | `ops.alert_lag`, `ops.alert_cleared`, both locales, same placeholders |
| `requirements.txt` | `aiohttp` pinned; it was already an implicit gift from aiogram, and the worker now serves HTTP on purpose |
| `docker/compose.yml` | `json-file` rotation on every service, worker `healthcheck` and `restart: unless-stopped` |
| `scripts/backup.sh`, `Makefile`, `README.md` | `pg_dump -Fc` with retention, `make health` / `metrics` / `backup` / `restore` |

`BACKUP_DIR` and `BACKUP_KEEP_DAYS` deliberately stay out of `Settings`: a shell script reads them, and the ban on `os.environ` (§11.1) is about Python. No second Python module reads the environment.

The backup runs inside the `db` container, which is the one place `pg_dump` is guaranteed to exist and to match the server version. The dump lands under a `.partial` name and is renamed only after a clean exit, and retention prunes *after* the dump, never before: pruning first would leave a directory holding neither a fresh backup nor the old ones the moment `pg_dump` fails.

## Boundaries

No Prometheus, Grafana or alertmanager in compose — the exposition is offered, and who scrapes it is the host's business. No per-user metrics: those are §23, they are counted from the journal and belong to the recipient. No `/readyz`: the worker accepts no inbound requests, so readiness and liveness are the same fact.

## Checks

`ruff check`, `ruff format --check`, `mypy app` and the full suite are green: 1747 passed, coverage 97%.
