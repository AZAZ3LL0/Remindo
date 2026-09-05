Closes the roadmap item **S12. Ops** (`tech.md` §15), the last one.

Builds on the v11 contract PR (#24), which is already in `main`.

## What the slice does

The worker ran five loops and told nobody anything. `run_loop` caught, logged and continued, so from outside a healthy worker and one whose planner had hung looked identical: the process was up either way. Nothing could say how far behind delivery was, container logs grew without a ceiling, and there was no backup.

- **`GET /healthz`** on the worker: `200` while every cycle is ticking, `503` naming the one that stopped. `docker compose ps worker` now reports `healthy`, and `restart: unless-stopped` acts on the red.
- **`GET /metrics`**: Prometheus text exposition of the three numbers §15 asked for — queue size, delivery lag, error share — plus per-cycle age and failure counters.
- **`ops.monitor`**, a fifth cycle, reading the queue once a minute and messaging `ADMIN_USER_IDS` when the lag crosses `ALERT_LAG_MINUTES`.
- **`scripts/backup.sh`** and **log rotation** on every compose service.

## The three decisions it turns on

**The heartbeat marks every attempt, failed ones included.** A database that blinks for a minute knocks over all five cycles while the loop keeps turning, and restarting the worker at that exact moment cures nothing and compounds into a restart loop. So `/healthz` never touches the database, and what it measures is the loop turning. A genuinely hung cycle is still caught from the other side: its attempt never returns, so its mark freezes and the budget runs out.

**The alert fires on the edge.** One message when the lag crosses the threshold, one when it comes back, nothing in between — an alert repeated every minute is not observation, it is a way to teach an operator to ignore it. That is also what makes the cycle idempotent: two runs in the same state send one message. The state lives in process memory because it belongs to the observer, not to the product; a restart costs one re-alert instead of a migration.

**Queue size counts what is overdue, not what is planned.** A reminder due tomorrow sits in the queue by design. Folding it in with what the dispatcher failed to send would measure popularity rather than delay.

## The window, and why it hangs off `fire_at`

The error share is `failed / (failed + delivered)` over `METRICS_WINDOW_MINUTES`, and the window is cut on `occurrences.fire_at` rather than `deliveries.updated_at`. `updated_at` is written by the database's own `now()`, while every other moment in the product comes from `Clock` (§8), and mixing two clocks for a metric is not a trade worth making. `fire_at` also asks the better question: of the things that came due in the last few minutes, what share never got out. Deliveries still queued count in neither half — they say nothing about transport yet — and an empty window reads as zero, not one, for the reason §23.2.6 gives about completion.

One query, not three: three would each see a different `now`, and a report whose lag and queue size disagree about the present is worse than none. A predicate bounds it to rows one of the counters can use, so it is not a full scan of every delivery ever made once a minute.

## Tests

| type | what it pins |
|---|---|
| contract | `/healthz` shape and its 200/503; `/metrics` parsed back the way a scraper reads it, including no scientific notation; the alert passes `FakeBotGateway` in both locales |
| idempotency | two `ops.monitor` runs on the same lag send one alert; catching up says so once and then falls silent |
| error path | `TelegramRetryAfter` leaves the edge unlatched for the next tick; `TelegramForbiddenError` on one admin does not cost the others their warning and mutes only that admin |
| property-based | lag never negative and zero on an empty queue; ratio in [0, 1]; staleness monotone in time and never below the floor; `decide_alert` a two-state machine that never reports the same edge twice |
| end to end | a failing cycle still keeps `/healthz` green and increments its failure counter; a cycle that stops ticking turns it red |

1792 passed, coverage 97%.

## Verified against the running stack

`docker compose ps worker` reports `healthy`; `/healthz` returns all five cycles with their ages and budgets; `/metrics` parses. `make backup` wrote a 35K custom-format dump, `make restore` brought back three reminders deleted from underneath it. Every container carries `json-file` with `max-size=10m, max-file=5`.

## Boundaries

No Prometheus or Grafana in compose: the exposition is offered, and who scrapes it is the host's business. No per-user metrics — those are §23, counted from the journal and owned by the recipient. No `/readyz`: the worker takes no inbound requests, so readiness and liveness are one fact.
