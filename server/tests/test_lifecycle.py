"""Tests for LifecycleEngine — decay computation and status transitions."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from amp_server.lifecycle import (
    STALE_THRESHOLD,
    ARCHIVE_STALE_DAYS,
    LifecycleEngine,
    compute_decay_score,
)
from amp_server.models import LifecycleStatus, MemoryType
from amp_server.storage.chroma import ChromaAdapter

from conftest import make_cell


# ---------------------------------------------------------------------------
# Decay formula
# ---------------------------------------------------------------------------


def test_decay_score_at_creation():
    """At t=0, decay_score = importance × confidence."""
    now = datetime.now(timezone.utc)
    cell = make_cell(importance=0.8, confidence=0.9, created_at=now)
    score = compute_decay_score(cell, now=now)
    assert abs(score - 0.8 * 0.9) < 1e-4


def test_decay_score_after_69_days():
    """With decay_rate=0.01, half-life ≈ 69.3 days. Score should be ~half."""
    now = datetime.now(timezone.utc)
    created = now - timedelta(days=69.3)
    cell = make_cell(importance=1.0, confidence=1.0, decay_rate=0.01, created_at=created)
    score = compute_decay_score(cell, now=now)
    expected = math.exp(-0.01 * 69.3)
    assert abs(score - expected) < 0.01


def test_decay_score_decreases_over_time():
    now = datetime.now(timezone.utc)
    cell_recent = make_cell(importance=0.8, confidence=1.0, created_at=now)
    cell_old = make_cell(
        importance=0.8, confidence=1.0, created_at=now - timedelta(days=100)
    )
    assert compute_decay_score(cell_recent, now=now) > compute_decay_score(
        cell_old, now=now
    )


def test_decay_score_zero_decay_rate():
    """Zero decay_rate means no decay — score stays constant."""
    now = datetime.now(timezone.utc)
    created = now - timedelta(days=1000)
    cell = make_cell(importance=0.7, confidence=0.8, decay_rate=0.0, created_at=created)
    score = compute_decay_score(cell, now=now)
    assert abs(score - 0.7 * 0.8) < 1e-4


# ---------------------------------------------------------------------------
# Status transitions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_active_to_stale_transition():
    """Cell with low decay score should transition from active to stale."""
    storage = ChromaAdapter()
    engine = LifecycleEngine(storage)

    old_date = datetime.now(timezone.utc) - timedelta(days=500)
    cell = make_cell(
        importance=0.3,
        confidence=0.5,
        decay_rate=0.01,
        created_at=old_date,
        status=LifecycleStatus.ACTIVE,
    )
    score = compute_decay_score(cell)
    assert score < STALE_THRESHOLD

    new_status = await engine.evaluate_cell(cell)
    assert new_status == LifecycleStatus.STALE


@pytest.mark.asyncio
async def test_active_stays_active_when_score_high():
    """Recent cell with high importance should remain active."""
    storage = ChromaAdapter()
    engine = LifecycleEngine(storage)

    cell = make_cell(
        importance=0.9,
        confidence=1.0,
        created_at=datetime.now(timezone.utc),
    )
    new_status = await engine.evaluate_cell(cell)
    assert new_status == LifecycleStatus.ACTIVE


@pytest.mark.asyncio
async def test_stale_to_archived_after_30_days():
    """Stale cell older than 30 days should transition to archived."""
    storage = ChromaAdapter()
    engine = LifecycleEngine(storage)

    old_date = datetime.now(timezone.utc) - timedelta(days=ARCHIVE_STALE_DAYS + 1)
    cell = make_cell(
        importance=0.1,
        confidence=0.1,
        created_at=old_date,
        status=LifecycleStatus.STALE,
    )
    new_status = await engine.evaluate_cell(cell)
    assert new_status == LifecycleStatus.ARCHIVED


@pytest.mark.asyncio
async def test_deleted_stays_deleted():
    """Deleted cells should never change status."""
    storage = ChromaAdapter()
    engine = LifecycleEngine(storage)

    cell = make_cell(status=LifecycleStatus.DELETED)
    new_status = await engine.evaluate_cell(cell)
    assert new_status == LifecycleStatus.DELETED


# ---------------------------------------------------------------------------
# process_all
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_all_transitions():
    """process_all should transition qualifying cells and return counts."""
    storage = ChromaAdapter()
    engine = LifecycleEngine(storage)

    old_date = datetime.now(timezone.utc) - timedelta(days=500)
    cell_will_stale = make_cell(
        importance=0.2,
        confidence=0.3,
        decay_rate=0.01,
        created_at=old_date,
        status=LifecycleStatus.ACTIVE,
        text="will go stale",
    )
    cell_stays_active = make_cell(
        importance=0.95,
        confidence=1.0,
        created_at=datetime.now(timezone.utc),
        text="stays active",
    )
    await storage.save(cell_will_stale)
    await storage.save(cell_stays_active)

    result = await engine.process_all()
    assert result["active_to_stale"] >= 1

    updated = await storage._get_raw(cell_will_stale.id)
    assert updated.lifecycle.status == LifecycleStatus.STALE
