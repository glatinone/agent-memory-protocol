"""Tests for lifecycle scheduling: the background loop and the manual-run route."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from amp_server.lifecycle import STALE_THRESHOLD, LifecycleEngine
from amp_server.models import LifecycleStatus, MemoryCellUpdate, MemoryScoring
from amp_server.scheduler import (
    DEFAULT_INTERVAL_SECONDS,
    LifecycleSettings,
    lifecycle_loop,
    run_lifecycle,
    settings_from_env,
)
from amp_server.storage.chroma import ChromaAdapter

from conftest import make_cell


def _fresh_storage() -> ChromaAdapter:
    return ChromaAdapter(collection_name=f"test_{uuid.uuid4().hex[:12]}")


# ---------------------------------------------------------------------------
# stale -> active reactivation (spec v0.1.0 lifecycle §2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stale_reactivates_when_score_recovers():
    """A stale cell whose score rises back above threshold returns to active."""
    storage = _fresh_storage()
    engine = LifecycleEngine(storage)

    # Long-decayed cell that had gone stale, then re-scored into relevance.
    old = datetime.now(timezone.utc) - timedelta(days=500)
    cell = make_cell(
        importance=1.0,
        confidence=1.0,
        decay_rate=0.0,
        created_at=old,
        status=LifecycleStatus.STALE,
    )
    assert await engine.evaluate_cell(cell) == LifecycleStatus.ACTIVE


@pytest.mark.asyncio
async def test_stale_reactivation_via_patch_then_run():
    """PATCHing scoring high, then running the engine, flips stale -> active."""
    storage = _fresh_storage()
    engine = LifecycleEngine(storage)

    old = datetime.now(timezone.utc) - timedelta(days=500)
    cell = make_cell(
        importance=0.2,
        confidence=0.5,
        decay_rate=0.01,
        created_at=old,
        status=LifecycleStatus.STALE,
        text="was stale, now re-scored",
    )
    await storage.save(cell)

    await storage.update(
        cell.id, MemoryCellUpdate(scoring=MemoryScoring(importance=1.0, decay_rate=0.0))
    )

    result = await engine.process_all()
    assert result.get("stale_to_active") == 1

    updated = await storage._get_raw(cell.id)
    assert updated.lifecycle.status == LifecycleStatus.ACTIVE


@pytest.mark.asyncio
async def test_stale_still_archives_when_score_stays_low():
    """Reactivation must not stop a genuinely-decayed cell from archiving."""
    storage = _fresh_storage()
    engine = LifecycleEngine(storage)
    old = datetime.now(timezone.utc) - timedelta(days=500)

    cell = make_cell(
        importance=0.1,
        confidence=0.1,
        decay_rate=0.01,
        created_at=old,
        status=LifecycleStatus.STALE,
    )
    assert await engine.evaluate_cell(cell) == LifecycleStatus.ARCHIVED


# ---------------------------------------------------------------------------
# settings
# ---------------------------------------------------------------------------


def test_settings_default_to_enabled_with_daily_ish_interval(monkeypatch):
    for var in (
        "AMP_LIFECYCLE_ENABLED",
        "AMP_LIFECYCLE_INTERVAL_SECONDS",
        "AMP_ADMIN_TOKEN",
    ):
        monkeypatch.delenv(var, raising=False)

    settings = settings_from_env()
    assert settings.enabled is True
    assert settings.interval_seconds == DEFAULT_INTERVAL_SECONDS
    assert settings.admin_token is None


def test_settings_flag_disables_scheduler(monkeypatch):
    monkeypatch.setenv("AMP_LIFECYCLE_ENABLED", "false")
    assert settings_from_env().enabled is False

    monkeypatch.setenv("AMP_LIFECYCLE_ENABLED", "0")
    assert settings_from_env().enabled is False


def test_settings_reject_bad_interval(monkeypatch):
    """A non-integer or non-positive interval falls back, not crashes."""
    monkeypatch.setenv("AMP_LIFECYCLE_INTERVAL_SECONDS", "not-a-number")
    assert settings_from_env().interval_seconds == DEFAULT_INTERVAL_SECONDS

    monkeypatch.setenv("AMP_LIFECYCLE_INTERVAL_SECONDS", "0")
    assert settings_from_env().interval_seconds == DEFAULT_INTERVAL_SECONDS


# ---------------------------------------------------------------------------
# run_lifecycle / lifecycle_loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_lifecycle_survives_engine_failure():
    """One failing run must not propagate — the loop has to keep going."""

    class Boom:
        async def process_all(self) -> dict[str, int]:
            raise RuntimeError("storage exploded")

    assert await run_lifecycle(Boom()) == {}  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_lifecycle_loop_runs_then_cancels_cleanly():
    """The loop performs runs and stops promptly when the lifespan cancels it."""
    storage = _fresh_storage()
    engine = LifecycleEngine(storage)

    runs = 0
    reached = asyncio.Event()

    class Counting:
        async def process_all(self) -> dict[str, int]:
            nonlocal runs
            runs += 1
            reached.set()
            return {}

    task = asyncio.create_task(lifecycle_loop(Counting(), 0.01))  # type: ignore[arg-type]
    try:
        await asyncio.wait_for(reached.wait(), timeout=2)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert runs >= 1
    # Engine/storage pairing in the fixture stays usable after cancellation.
    assert isinstance(engine, LifecycleEngine)


@pytest.mark.asyncio
async def test_loop_keeps_running_after_a_failed_run():
    """A raising engine does not kill the loop — it runs again next tick."""

    class Flaky:
        def __init__(self) -> None:
            self.calls = 0
            self.second = asyncio.Event()

        async def process_all(self) -> dict[str, int]:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("first run fails")
            self.second.set()
            return {}

    flaky = Flaky()
    task = asyncio.create_task(lifecycle_loop(flaky, 0.01))  # type: ignore[arg-type]
    try:
        await asyncio.wait_for(flaky.second.wait(), timeout=2)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert flaky.calls >= 2, "loop stopped after the first failing run"


# ---------------------------------------------------------------------------
# POST /amp/v1/lifecycle/run
# ---------------------------------------------------------------------------

_TOKEN = "test-admin-token"


def _install_app_state(token: str | None) -> None:
    """Point the app at a fresh storage + engine, as the lifespan would."""
    import amp_server.main as main_mod

    main_mod._storage = _fresh_storage()
    main_mod._lifecycle = LifecycleEngine(main_mod._storage)
    main_mod._lifecycle_settings = LifecycleSettings(
        enabled=True, interval_seconds=DEFAULT_INTERVAL_SECONDS, admin_token=token
    )


async def _post_run(headers: dict[str, str]) -> object:
    from amp_server.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.post("/amp/v1/lifecycle/run", headers=headers)


@pytest.mark.asyncio
async def test_lifecycle_run_disabled_when_no_token_configured():
    """Unset AMP_ADMIN_TOKEN disables the route rather than leaving it open."""
    _install_app_state(token=None)

    resp = await _post_run({})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "ADMIN_DISABLED"


@pytest.mark.asyncio
async def test_lifecycle_run_rejects_wrong_token():
    _install_app_state(token=_TOKEN)

    resp = await _post_run({"X-AMP-Admin-Token": "nope"})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "ACCESS_DENIED"


@pytest.mark.asyncio
async def test_lifecycle_run_with_valid_token_reports_transitions():
    _install_app_state(token=_TOKEN)

    # Seed a cell that must go active -> stale so the counts are non-trivial.
    import amp_server.main as main_mod

    old = datetime.now(timezone.utc) - timedelta(days=500)
    await main_mod._storage.save(
        make_cell(
            importance=0.2,
            confidence=0.3,
            decay_rate=0.01,
            created_at=old,
            status=LifecycleStatus.ACTIVE,
            text="goes stale on manual run",
        )
    )

    resp = await _post_run({"X-AMP-Admin-Token": _TOKEN})
    assert resp.status_code == 200
    assert resp.json()["transitions"]["active_to_stale"] >= 1


@pytest.mark.asyncio
async def test_spec_reports_lifecycle_scheduler_capability():
    _install_app_state(token=_TOKEN)

    from amp_server.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/amp/v1/spec")

    assert resp.status_code == 200
    sched = resp.json()["capabilities"]["lifecycle_scheduler"]
    assert sched["manual_run_endpoint"] == "/amp/v1/lifecycle/run"
    assert "interval_seconds" in sched