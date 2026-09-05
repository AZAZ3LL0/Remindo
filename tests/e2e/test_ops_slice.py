"""S12 end to end: the worker loop, its heartbeat and what /healthz answers.

Acceptance criteria of tech.md 15 (S12): the worker can be asked whether it is
still turning, and the answer must survive a broken database while still
catching a cycle that stopped.
"""

import asyncio
import contextlib
from datetime import timedelta

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app.domain.contracts import HealthStatus, JobId
from app.domain.ops import stale_after
from app.services.ops import MonitorState
from app.worker.health import Heartbeats, build_app
from app.worker.main import run_loop
from tests.conftest import FROZEN_NOW

INTERVAL = 60.0


@pytest.fixture
def beats(fake_clock) -> Heartbeats:
    registry = Heartbeats()
    registry.register(JobId.PLANNER_MATERIALIZE, INTERVAL, fake_clock.now())
    return registry


@pytest.fixture
async def client(fake_clock, beats):
    app = build_app(fake_clock, beats, MonitorState())
    async with TestClient(TestServer(app)) as started:
        yield started


async def turn_once(job, cycle, fake_clock, beats) -> None:
    """Let the loop complete exactly one attempt, then stop it.

    The waits are scheduling yields, not delays: `FakeClock` never moves on its
    own, so nothing here depends on wall time.
    """
    attempted = asyncio.Event()

    async def once() -> object:
        attempted.set()
        return await cycle()

    task = asyncio.create_task(run_loop(job, INTERVAL, once, fake_clock, beats))
    await attempted.wait()
    await asyncio.sleep(0)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def test_a_healthy_worker_answers_two_hundred(client, beats, fake_clock):
    async def cycle() -> object:
        return None

    fake_clock.advance(timedelta(seconds=30))
    await turn_once(JobId.PLANNER_MATERIALIZE, cycle, fake_clock, beats)

    response = await client.get("/healthz")
    payload = await response.json()

    assert response.status == 200
    assert payload["status"] == HealthStatus.OK.value
    assert payload["cycles"][0]["failures"] == 0


async def test_a_failing_cycle_still_proves_the_loop_is_turning(client, beats, fake_clock):
    """A database that blinks must not read as a hung worker: restarting the
    process then cures nothing and repeats forever (tech.md 24.1)."""

    async def cycle() -> object:
        raise RuntimeError("database blinked")

    fake_clock.advance(timedelta(minutes=5))
    await turn_once(JobId.PLANNER_MATERIALIZE, cycle, fake_clock, beats)

    response = await client.get("/healthz")
    payload = await response.json()

    assert response.status == 200
    assert payload["cycles"][0]["failures"] == 1
    assert payload["cycles"][0]["last_tick_at"].startswith("2026-06-01T12:05")


async def test_a_cycle_that_stops_ticking_turns_the_healthcheck_red(client, beats, fake_clock):
    budget = stale_after(beats.all()[0])
    fake_clock.set(FROZEN_NOW + budget + timedelta(seconds=1))

    response = await client.get("/healthz")
    payload = await response.json()

    assert response.status == 503
    assert payload["status"] == HealthStatus.STALE.value
    assert payload["cycles"][0]["stale"] is True


async def test_metrics_answer_before_the_monitor_has_read_anything(client):
    """The endpoint never touches the database, so it starts up with the
    cycles alone and gains the queue numbers on the first monitor tick."""
    response = await client.get("/metrics")
    body = await response.text()

    assert response.status == 200
    assert "reminder_worker_up 1" in body
    assert "reminder_delivery_lag_seconds" not in body
