"""LifecycleEngine scheduling — the run schedule the spec leaves implementation-defined.

`spec/v0.1.0/lifecycle.md` §2 says `process_all` is expected to run on a
scheduled interval but deliberately does not fix one. This module supplies the
reference server's answer: a background asyncio task started from the FastAPI
`lifespan`, plus the single guarded `run_lifecycle()` entry point that the admin
route calls so an external cron or an operator can trigger the same run.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field

from amp_server.lifecycle import LifecycleEngine

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 3600


@dataclass(frozen=True)
class LifecycleSettings:
    """Resolved lifecycle scheduling configuration."""

    enabled: bool
    interval_seconds: int
    admin_token: str | None
    purge_retention: bool


@dataclass(frozen=True)
class LifecycleRun:
    """What one pass did.

    `purged` is 0 unless the retention pass is enabled, so the same shape serves
    both configurations and a caller never has to check for a missing key.
    """

    transitions: dict[str, int] = field(default_factory=dict)
    purged: int = 0


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


def settings_from_env() -> LifecycleSettings:
    """Read lifecycle settings from the environment.

    `AMP_LIFECYCLE_ENABLED` defaults on so a fresh `docker compose up -d` decays
    cells without extra configuration. `AMP_ADMIN_TOKEN` gates the manual-run
    route; leaving it unset disables that route rather than leaving it open.

    `AMP_PURGE_RETENTION` defaults *off*, alone among these. Spec §6.3 sets a
    minimum retention rather than a deadline, so holding a deleted cell for longer
    is compliant - and a server that starts erasing data by default after an
    upgrade is a worse default than one that keeps it until an operator opts in.
    """
    raw_interval = os.environ.get("AMP_LIFECYCLE_INTERVAL_SECONDS", "")
    try:
        interval = int(raw_interval) if raw_interval else DEFAULT_INTERVAL_SECONDS
    except ValueError:
        logger.warning(
            "AMP_LIFECYCLE_INTERVAL_SECONDS=%r is not an integer; using %d",
            raw_interval,
            DEFAULT_INTERVAL_SECONDS,
        )
        interval = DEFAULT_INTERVAL_SECONDS
    if interval <= 0:
        logger.warning(
            "AMP_LIFECYCLE_INTERVAL_SECONDS must be positive; using %d",
            DEFAULT_INTERVAL_SECONDS,
        )
        interval = DEFAULT_INTERVAL_SECONDS

    return LifecycleSettings(
        enabled=_env_flag("AMP_LIFECYCLE_ENABLED", True),
        interval_seconds=interval,
        admin_token=os.environ.get("AMP_ADMIN_TOKEN") or None,
        purge_retention=_env_flag("AMP_PURGE_RETENTION", False),
    )


async def run_lifecycle(
    engine: LifecycleEngine, settings: LifecycleSettings
) -> LifecycleRun:
    """Run one pass: decay, then retention purging when it is enabled.

    A single failed pass must not kill the background task: an unhandled
    exception there would end all decay for the process lifetime with no signal
    beyond a traceback. Errors are logged and reported as an empty result so
    callers can distinguish "nothing to do" from "crashed".
    """
    try:
        transitions = await engine.process_all()
        purged = await engine.purge_expired() if settings.purge_retention else 0
    except Exception:  # noqa: BLE001 — see docstring: keep the loop alive
        logger.exception("Lifecycle run failed; continuing")
        return LifecycleRun()
    logger.info("Lifecycle run complete: %s, purged=%d", transitions, purged)
    return LifecycleRun(transitions=transitions, purged=purged)


async def lifecycle_loop(engine: LifecycleEngine, settings: LifecycleSettings) -> None:
    """Sleep-then-run forever. Cancelled by the lifespan on shutdown.

    Sleeping first avoids paying a run's latency at startup and racing the first
    requests; a fresh database has nothing to decay, and the admin route covers
    the "run it now" case.

    Takes the whole settings object rather than the interval, so the retention
    flag reaches the pass by the same route the interval does instead of being
    read from the environment a second time.
    """
    while True:
        await asyncio.sleep(settings.interval_seconds)
        await run_lifecycle(engine, settings)
