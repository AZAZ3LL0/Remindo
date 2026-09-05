"""Entry point of the `worker` process. It plans and delivers, never polls updates."""

import asyncio
from collections.abc import Awaitable, Callable

from app.core.clock import Clock
from app.core.di import AppContext, build_context
from app.core.logging import get_logger
from app.domain.contracts import JobId
from app.services.ops import MonitorState
from app.worker import digest, dispatcher, ops, planner, reaper
from app.worker.health import Heartbeats, serve

_log = get_logger(__name__)

#: Sleep between failed cycles, so a broken database does not spin the loop.
ERROR_BACKOFF_SECONDS = 5.0


async def run_loop(
    job: JobId,
    interval: float,
    cycle: Callable[[], Awaitable[object]],
    clock: Clock,
    beats: Heartbeats,
) -> None:
    while True:
        failed = False
        try:
            await cycle()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            failed = True
            _log.error("worker.cycle_failed", job=job.value, error=type(error).__name__)
        # The mark goes down on every attempt, failed ones included: what it
        # measures is the loop turning, and a database that blinks must not
        # look like a hung worker (tech.md 24.1).
        beats.mark(job, clock.now(), failed=failed)
        await asyncio.sleep(ERROR_BACKOFF_SECONDS if failed else interval)


async def run() -> None:
    context: AppContext = build_context()
    settings = context.settings
    _log.info("worker.start", env=settings.env)

    beats = Heartbeats()
    monitor = MonitorState()
    cycles: list[tuple[JobId, float, Callable[[], Awaitable[object]]]] = [
        (
            JobId.PLANNER_MATERIALIZE,
            settings.planner_interval_seconds,
            lambda: planner.run_once(context.session_factory, context.clock, settings),
        ),
        (
            JobId.DISPATCHER_DELIVER,
            settings.dispatch_interval_seconds,
            lambda: dispatcher.run_once(
                context.session_factory, context.clock, context.gateway, settings
            ),
        ),
        (
            JobId.REAPER_SWEEP,
            settings.planner_interval_seconds,
            lambda: reaper.run_once(context.session_factory, context.clock, context.gateway),
        ),
        (
            # A weekly message needs no period of its own: the sweep interval
            # is already a minute, and a second name for the same number is
            # only a way to desynchronise them.
            JobId.DIGEST_SEND,
            settings.planner_interval_seconds,
            lambda: digest.run_once(
                context.session_factory, context.clock, context.gateway, settings
            ),
        ),
        (
            JobId.OPS_MONITOR,
            settings.planner_interval_seconds,
            lambda: ops.run_once(
                context.session_factory, context.clock, context.gateway, settings, monitor
            ),
        ),
    ]

    started = context.clock.now()
    for job, interval, _ in cycles:
        # Registered before the first tick, or every cycle would read as stale
        # for as long as it takes it to finish its first pass.
        beats.register(job, interval, started)

    runner = await serve(context.clock, beats, monitor, settings.health_host, settings.health_port)
    _log.info("worker.health_up", host=settings.health_host, port=settings.health_port)

    try:
        async with asyncio.TaskGroup() as group:
            for job, interval, cycle in cycles:
                group.create_task(run_loop(job, interval, cycle, context.clock, beats))
    finally:
        await runner.cleanup()
        await context.shutdown()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
