"""Worker healthcheck and metrics endpoints (tech.md 24.1, 24.2).

Both are machine-facing, so nothing here goes through `T(...)`: the readers are
a docker healthcheck and a scraper, not a person.
"""

from datetime import datetime
from typing import Any

from aiohttp import web

from app.core.clock import Clock
from app.domain.contracts import HealthStatus, JobId
from app.domain.ops import CycleBeat, health_status, is_stale, stale_after
from app.services.ops import MonitorState

#: Prefix every exposed series shares, so a scraper can select the whole app.
METRIC_PREFIX = "reminder"


class Heartbeats:
    """Last attempt of every worker cycle.

    The mark is stamped on each attempt, successful or failed: `run_loop`
    catches and continues, so the loop turning is exactly what this measures. A
    database that blinks knocks the cycles over without stopping the loop, and
    restarting the worker then would cure nothing and repeat forever. A truly
    hung cycle is still caught: its attempt never returns, so its mark freezes.
    """

    def __init__(self) -> None:
        self._beats: dict[JobId, CycleBeat] = {}

    def register(self, job: JobId, interval_seconds: float, now: datetime) -> None:
        """Start a cycle's clock at startup, so it is not stale before its first tick."""
        self._beats[job] = CycleBeat(job=job, interval_seconds=interval_seconds, last_tick_at=now)

    def mark(self, job: JobId, now: datetime, *, failed: bool = False) -> None:
        beat = self._beats[job]
        self._beats[job] = CycleBeat(
            job=beat.job,
            interval_seconds=beat.interval_seconds,
            last_tick_at=now,
            failures=beat.failures + (1 if failed else 0),
        )

    def all(self) -> tuple[CycleBeat, ...]:
        return tuple(self._beats.values())


def health_payload(beats: tuple[CycleBeat, ...], now: datetime) -> dict[str, Any]:
    status = health_status(beats, now)
    return {
        "status": status.value,
        "cycles": [
            {
                "job": beat.job.value,
                "last_tick_at": beat.last_tick_at.isoformat(),
                "age_seconds": round((now - beat.last_tick_at).total_seconds(), 3),
                "stale_after_seconds": round(stale_after(beat).total_seconds(), 3),
                "stale": is_stale(beat, now),
                "failures": beat.failures,
            }
            for beat in beats
        ],
    }


def render_metrics(beats: tuple[CycleBeat, ...], state: MonitorState, now: datetime) -> str:
    """Prometheus text exposition of the three numbers plus the cycles.

    The report comes from the last `ops.monitor` tick and is not read from the
    database here: a scrape must not be able to load the very queue it watches.
    Its age is exposed too, so a stuck cycle shows up in the exposition itself.
    """
    lines: list[str] = []
    healthy = health_status(beats, now) is HealthStatus.OK
    _gauge(lines, "worker_up", "Worker cycles are all ticking on time.", float(healthy))

    report = state.report
    if report is not None:
        _gauge(
            lines,
            "queue_due_deliveries",
            "Deliveries past their next attempt time.",
            float(report.queue_size),
        )
        _gauge(
            lines,
            "delivery_lag_seconds",
            "Age of the oldest delivery still waiting.",
            report.lag.total_seconds(),
        )
        _gauge(
            lines,
            "delivery_error_ratio",
            "Share of recent outcomes that never reached Telegram.",
            report.error_ratio,
        )
        _gauge(
            lines,
            "report_age_seconds",
            "Time since ops.monitor last read the queue.",
            (now - report.taken_at).total_seconds(),
        )

    _series(
        lines,
        "cycle_age_seconds",
        "Time since a worker cycle last attempted its work.",
        [(beat.job.value, (now - beat.last_tick_at).total_seconds()) for beat in beats],
    )
    _series(
        lines,
        "cycle_failures_total",
        "Attempts a worker cycle has ended in an exception.",
        [(beat.job.value, float(beat.failures)) for beat in beats],
        kind="counter",
    )
    return "".join(lines)


def build_app(clock: Clock, beats: Heartbeats, state: MonitorState) -> web.Application:
    async def healthz(_request: web.Request) -> web.Response:
        now = clock.now()
        payload = health_payload(beats.all(), now)
        # 503 is the whole point: docker restarts on it, and a body nobody
        # parses would leave the operator guessing which cycle stopped.
        ok = payload["status"] == HealthStatus.OK.value
        return web.json_response(payload, status=200 if ok else 503)

    async def metrics(_request: web.Request) -> web.Response:
        body = render_metrics(beats.all(), state, clock.now())
        return web.Response(text=body, content_type="text/plain", charset="utf-8")

    app = web.Application()
    app.add_routes([web.get("/healthz", healthz), web.get("/metrics", metrics)])
    return app


async def serve(
    clock: Clock, beats: Heartbeats, state: MonitorState, host: str, port: int
) -> web.AppRunner:
    runner = web.AppRunner(build_app(clock, beats, state), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, host=host, port=port).start()
    return runner


def _gauge(lines: list[str], name: str, help_text: str, value: float) -> None:
    _series(lines, name, help_text, [(None, value)])


def _series(
    lines: list[str],
    name: str,
    help_text: str,
    points: list[tuple[str | None, float]],
    kind: str = "gauge",
) -> None:
    full = f"{METRIC_PREFIX}_{name}"
    lines.append(f"# HELP {full} {help_text}\n")
    lines.append(f"# TYPE {full} {kind}\n")
    for job, value in points:
        label = "" if job is None else f'{{job="{job}"}}'
        lines.append(f"{full}{label} {_number(value)}\n")


def _number(value: float) -> str:
    """Plain decimal, never scientific notation: 1e-05 is legal and unreadable."""
    return f"{value:.6f}".rstrip("0").rstrip(".")
