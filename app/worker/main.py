"""Entry point of the `worker` process. It plans and delivers, never polls updates."""

import asyncio
from collections.abc import Awaitable, Callable

from app.core.di import AppContext, build_context
from app.core.logging import get_logger
from app.domain.contracts import JobId
from app.worker import dispatcher, planner, reaper

_log = get_logger(__name__)

#: Sleep between failed cycles, so a broken database does not spin the loop.
ERROR_BACKOFF_SECONDS = 5.0


async def run_loop(job: JobId, interval: float, cycle: Callable[[], Awaitable[object]]) -> None:
    while True:
        try:
            await cycle()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            _log.error("worker.cycle_failed", job=job.value, error=type(error).__name__)
            await asyncio.sleep(ERROR_BACKOFF_SECONDS)
            continue
        await asyncio.sleep(interval)


async def run() -> None:
    context: AppContext = build_context()
    settings = context.settings
    _log.info("worker.start", env=settings.env)

    try:
        async with asyncio.TaskGroup() as group:
            group.create_task(
                run_loop(
                    JobId.PLANNER_MATERIALIZE,
                    settings.planner_interval_seconds,
                    lambda: planner.run_once(context.session_factory, context.clock, settings),
                )
            )
            group.create_task(
                run_loop(
                    JobId.DISPATCHER_DELIVER,
                    settings.dispatch_interval_seconds,
                    lambda: dispatcher.run_once(
                        context.session_factory, context.clock, context.gateway, settings
                    ),
                )
            )
            group.create_task(
                run_loop(
                    JobId.REAPER_SWEEP,
                    settings.planner_interval_seconds,
                    lambda: reaper.run_once(
                        context.session_factory, context.clock, context.gateway
                    ),
                )
            )
    finally:
        await context.shutdown()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
