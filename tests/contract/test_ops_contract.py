"""Seams of the ops slice (tech.md 24.1, 24.2, 24.8).

The endpoints are a contract with a docker healthcheck and a scraper, so what
they answer is checked the way a payload is: by parsing it back, not by reading
the code that wrote it.
"""

from datetime import timedelta

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app.domain.contracts import HealthStatus, JobId
from app.domain.ops import AlertKind, CycleBeat, OpsReport, stale_after
from app.gateways.bot_gateway import OutgoingMessage
from app.gateways.fakes import validate_outgoing
from app.services.ops import MonitorState, render_alert
from app.worker.health import build_app, render_metrics
from tests.conftest import FROZEN_NOW

REPORT = OpsReport(
    taken_at=FROZEN_NOW,
    queue_size=42,
    lag=timedelta(minutes=7, seconds=30),
    error_ratio=0.125,
)


def beats(*, ago=timedelta(0)):
    return (
        CycleBeat(
            job=JobId.PLANNER_MATERIALIZE,
            interval_seconds=60.0,
            last_tick_at=FROZEN_NOW - ago,
        ),
        CycleBeat(
            job=JobId.DISPATCHER_DELIVER,
            interval_seconds=10.0,
            last_tick_at=FROZEN_NOW,
            failures=3,
        ),
    )


def parse_exposition(body: str) -> dict[str, float]:
    """Prometheus text format, read back the way a scraper reads it."""
    samples: dict[str, float] = {}
    for line in body.splitlines():
        if not line or line.startswith("#"):
            continue
        name, _, value = line.rpartition(" ")
        samples[name.strip()] = float(value)
    return samples


class StaticBeats:
    """The registry's read side is all the endpoints use."""

    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


@pytest.fixture
async def client(fake_clock):
    state = MonitorState(report=REPORT)
    holder = StaticBeats(beats())
    async with TestClient(TestServer(build_app(fake_clock, holder, state))) as started:
        yield started, holder, state


# --- /healthz ---------------------------------------------------------------


async def test_healthz_answers_ok_while_every_cycle_keeps_ticking(client):
    started, _, _ = client

    response = await started.get("/healthz")
    payload = await response.json()

    assert response.status == 200
    assert payload["status"] == HealthStatus.OK.value
    assert {cycle["job"] for cycle in payload["cycles"]} == {
        JobId.PLANNER_MATERIALIZE.value,
        JobId.DISPATCHER_DELIVER.value,
    }
    assert all(cycle["stale"] is False for cycle in payload["cycles"])


async def test_healthz_answers_503_and_names_the_cycle_that_stopped(client):
    """A body nobody can read would leave the operator guessing which one."""
    started, holder, _ = client
    overdue = stale_after(beats()[0]) + timedelta(seconds=1)
    holder._items = beats(ago=overdue)

    response = await started.get("/healthz")
    payload = await response.json()

    assert response.status == 503
    assert payload["status"] == HealthStatus.STALE.value
    stalled = [cycle["job"] for cycle in payload["cycles"] if cycle["stale"]]
    assert stalled == [JobId.PLANNER_MATERIALIZE.value]


async def test_a_worker_with_no_cycles_registered_yet_is_not_reported_ill(client):
    started, holder, _ = client
    holder._items = ()

    response = await started.get("/healthz")

    assert response.status == 200
    assert (await response.json())["cycles"] == []


# --- /metrics ---------------------------------------------------------------


async def test_metrics_serve_plain_text_a_scraper_can_parse(client):
    started, _, _ = client

    response = await started.get("/metrics")
    body = await response.text()

    assert response.status == 200
    assert response.content_type == "text/plain"
    assert parse_exposition(body)


def test_the_exposition_carries_the_three_numbers_of_the_roadmap():
    samples = parse_exposition(render_metrics(beats(), MonitorState(report=REPORT), FROZEN_NOW))

    assert samples["reminder_queue_due_deliveries"] == 42
    assert samples["reminder_delivery_lag_seconds"] == 450
    assert samples["reminder_delivery_error_ratio"] == 0.125


def test_every_cycle_reports_its_age_and_its_failures():
    samples = parse_exposition(render_metrics(beats(), MonitorState(report=REPORT), FROZEN_NOW))

    assert samples['reminder_cycle_age_seconds{job="planner.materialize"}'] == 0
    assert samples['reminder_cycle_failures_total{job="dispatcher.deliver"}'] == 3


def test_a_stalled_cycle_shows_up_in_the_exposition_itself():
    """Scrapers alert on this without ever calling the healthcheck."""
    overdue = stale_after(beats()[0]) + timedelta(seconds=1)
    samples = parse_exposition(
        render_metrics(beats(ago=overdue), MonitorState(report=REPORT), FROZEN_NOW)
    )

    assert samples["reminder_worker_up"] == 0


def test_metrics_hold_no_report_before_the_first_monitor_tick():
    """The endpoint never reads the queue itself, so it has nothing to show."""
    samples = parse_exposition(render_metrics(beats(), MonitorState(), FROZEN_NOW))

    assert "reminder_delivery_lag_seconds" not in samples
    assert samples["reminder_worker_up"] == 1


def test_numbers_never_reach_a_scraper_in_scientific_notation():
    tiny = OpsReport(taken_at=FROZEN_NOW, queue_size=0, lag=timedelta(0), error_ratio=0.000001)

    body = render_metrics(beats(), MonitorState(report=tiny), FROZEN_NOW)

    assert "e-" not in body
    assert parse_exposition(body)["reminder_delivery_error_ratio"] == 0.000001


# --- the alert message ------------------------------------------------------


@pytest.mark.parametrize("kind", list(AlertKind))
@pytest.mark.parametrize("lang", ["ru", "en"])
def test_an_alert_is_a_message_telegram_would_accept(kind, lang):
    message = OutgoingMessage(chat_id=777, text=render_alert(kind, REPORT, lang), keyboard=None)

    validate_outgoing(message)


def test_the_alert_rounds_the_lag_up():
    """A lag of 7.5 minutes printed as 7 reads like the threshold held."""
    text = render_alert(AlertKind.RAISED, REPORT, "en")

    assert "8 min" in text
    assert "42 queued" in text
    assert "12% failing" in text
