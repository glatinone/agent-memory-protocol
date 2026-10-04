"""Rate-limiting scoring edits, per cell (RFC-AMP-001 §5).

The RFC lists decay-score manipulation as a threat and asks implementations to
rate-limit how often one cell's `scoring` may be rewritten: a caller looping on it
can hold a cell `active` past its relevance window, or drive a competing memory
into archive. Two halves matter here - that a loop is refused, and that ordinary
editing is not caught by the refusal. A limit that refuses both is not a
mitigation, it is an outage.
"""

from __future__ import annotations

import pytest
from conftest import install_app_state, make_cell
from httpx import ASGITransport, AsyncClient, Response

from amp_server.models import LifecycleStatus, MemoryCellUpdate, MemoryScoring
from amp_server.ratelimit import (
    DEFAULT_MAX_PATCHES,
    DEFAULT_WINDOW_SECONDS,
    ScoringPatchLimit,
    ScoringPatchLimiter,
    limit_from_env,
    patch_touches_scoring,
)

_AGENT = "agent-ratelimit"


class FakeClock:
    """A clock the test moves, so a window costs no wall time."""

    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _install_app(
    limit: ScoringPatchLimit | None = None, clock: FakeClock | None = None
) -> ScoringPatchLimiter:
    """Fresh state with the budget and clock this test wants."""
    return install_app_state(
        scoring_limit=limit, scoring_clock=clock or FakeClock()
    ).limiter


async def _client() -> AsyncClient:
    import amp_server.main as main_mod

    return AsyncClient(
        transport=ASGITransport(app=main_mod.app), base_url="http://test"
    )


async def _store_cell(text: str = "scored cell") -> str:
    import amp_server.main as main_mod

    cell = make_cell(owner_id=_AGENT, created_by=_AGENT, text=text)
    await main_mod.get_storage().save(cell)
    return cell.id


def _scoring(importance: float = 0.9) -> dict:
    return {"scoring": {"importance": importance, "confidence": 1.0, "decay_rate": 0.0}}


def _headers() -> dict[str, str]:
    return {"X-AMP-Agent-ID": _AGENT}


async def _patch(memory_id: str, body: dict) -> Response:
    async with await _client() as client:
        return await client.patch(
            f"/amp/v1/memories/{memory_id}", json=body, headers=_headers()
        )


# ---------------------------------------------------------------------------
# The rule itself
# ---------------------------------------------------------------------------


def test_a_null_scoring_field_costs_nothing():
    """The budget is spent by writes, and `{"scoring": null}` writes nothing."""
    assert patch_touches_scoring(
        MemoryCellUpdate.model_validate({"scoring": None})
    ) is (False)
    assert (
        patch_touches_scoring(
            MemoryCellUpdate.model_validate({"content": {"text": "x"}})
        )
        is False
    )
    assert not patch_touches_scoring(MemoryCellUpdate.model_validate({"scoring": None}))
    assert not patch_touches_scoring(
        MemoryCellUpdate.model_validate({"content": {"text": "x"}})
    )
    assert patch_touches_scoring(MemoryCellUpdate(scoring=MemoryScoring()))


def test_the_limit_refuses_past_its_budget_and_says_how_long():
    clock = FakeClock()
    limiter = ScoringPatchLimiter(
        ScoringPatchLimit(max_patches=2, window_seconds=60), clock=clock
    )

    assert limiter.check_and_record("mem_a") == 0
    assert limiter.check_and_record("mem_a") == 0
    assert limiter.check_and_record("mem_a") == 60  # the first edit ages out then


def test_a_refusal_does_not_extend_the_lockout():
    """Otherwise hammering would push the caller's own deadline back."""
    clock = FakeClock()
    limiter = ScoringPatchLimiter(
        ScoringPatchLimit(max_patches=1, window_seconds=60), clock=clock
    )
    limiter.check_and_record("mem_a")

    clock.advance(10)
    first_refusal = limiter.check_and_record("mem_a")
    clock.advance(10)
    second_refusal = limiter.check_and_record("mem_a")

    assert first_refusal == 50
    assert second_refusal == 40, "the wait must shrink, not grow"


def test_the_window_is_per_cell():
    clock = FakeClock()
    limiter = ScoringPatchLimiter(
        ScoringPatchLimit(max_patches=1, window_seconds=60), clock=clock
    )
    limiter.check_and_record("mem_a")

    assert limiter.check_and_record("mem_a") == 60
    assert limiter.check_and_record("mem_b") == 0


def test_the_budget_returns_once_the_window_passes():
    clock = FakeClock()
    limiter = ScoringPatchLimiter(
        ScoringPatchLimit(max_patches=1, window_seconds=60), clock=clock
    )
    limiter.check_and_record("mem_a")

    clock.advance(59)
    assert limiter.check_and_record("mem_a") == 1
    clock.advance(1)
    assert limiter.check_and_record("mem_a") == 0


def test_cells_are_forgotten_after_a_purge():
    limiter = ScoringPatchLimiter(ScoringPatchLimit(max_patches=1, window_seconds=60))

    limiter.check_and_record("mem_a")
    assert limiter.tracked_cells() == 1

    limiter.forget("mem_a")
    assert limiter.tracked_cells() == 0


def test_tracking_is_bounded():
    """An unbounded counter map is a slow leak in a long-running server."""
    limiter = ScoringPatchLimiter(
        ScoringPatchLimit(max_patches=1, window_seconds=60), max_tracked_cells=3
    )

    for index in range(10):
        limiter.check_and_record(f"mem_{index}")

    assert limiter.tracked_cells() == 3


def test_a_disabled_limit_never_refuses():
    clock = FakeClock()
    limiter = ScoringPatchLimiter(
        ScoringPatchLimit(max_patches=0, window_seconds=60), clock=clock
    )

    for _ in range(50):
        assert limiter.check_and_record("mem_a") == 0
    assert ScoringPatchLimit(max_patches=0).to_json() is None


def test_the_settings_default_to_the_documented_numbers(monkeypatch):
    for var in ("AMP_SCORING_PATCH_LIMIT", "AMP_SCORING_PATCH_WINDOW_SECONDS"):
        monkeypatch.delenv(var, raising=False)

    limit = limit_from_env()
    assert limit.max_patches == DEFAULT_MAX_PATCHES
    assert limit.window_seconds == DEFAULT_WINDOW_SECONDS
    assert limit.enabled is True


def test_a_bad_setting_falls_back_rather_than_stopping_the_server(monkeypatch):
    """A wrong number here degrades a mitigation; it does not corrupt data."""
    monkeypatch.setenv("AMP_SCORING_PATCH_LIMIT", "not-a-number")
    assert limit_from_env().max_patches == DEFAULT_MAX_PATCHES

    monkeypatch.setenv("AMP_SCORING_PATCH_LIMIT", "-1")
    assert limit_from_env().max_patches == DEFAULT_MAX_PATCHES

    monkeypatch.setenv("AMP_SCORING_PATCH_LIMIT", "0")
    assert limit_from_env().enabled is False


# ---------------------------------------------------------------------------
# Over HTTP
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_loop_on_scoring_is_refused_with_a_retry_after():
    _install_app(ScoringPatchLimit(max_patches=2, window_seconds=3600))
    cell_id = await _store_cell()

    first = await _patch(cell_id, _scoring(0.9))
    second = await _patch(cell_id, _scoring(0.8))
    third = await _patch(cell_id, _scoring(0.7))

    assert [first.status_code, second.status_code] == [200, 200]
    assert third.status_code == 429
    assert third.json()["error"]["code"] == "RATE_LIMITED"
    assert third.headers["Retry-After"] == "3600"
    # The refused write did not land.
    assert third.json()["error"]["details"]["retry_after_seconds"] == 3600


@pytest.mark.asyncio
async def test_ordinary_edits_are_not_counted():
    """The limit is about `scoring`; refusing text edits would be an outage."""
    _install_app(ScoringPatchLimit(max_patches=1, window_seconds=3600))
    cell_id = await _store_cell()

    assert (await _patch(cell_id, _scoring(0.9))).status_code == 200
    for index in range(5):
        response = await _patch(cell_id, {"content": {"text": f"rewritten {index}"}})
        assert response.status_code == 200, f"edit {index} was counted as scoring"

    assert (await _patch(cell_id, _scoring(0.5))).status_code == 429


@pytest.mark.asyncio
async def test_one_cell_exhausting_its_budget_does_not_block_another():
    _install_app(ScoringPatchLimit(max_patches=1, window_seconds=3600))
    busy = await _store_cell("busy")
    other = await _store_cell("other")

    assert (await _patch(busy, _scoring(0.9))).status_code == 200
    assert (await _patch(busy, _scoring(0.8))).status_code == 429
    assert (await _patch(other, _scoring(0.8))).status_code == 200


@pytest.mark.asyncio
async def test_the_budget_returns_when_the_window_passes_over_http():
    clock = FakeClock()
    _install_app(ScoringPatchLimit(max_patches=1, window_seconds=60), clock=clock)
    cell_id = await _store_cell()

    assert (await _patch(cell_id, _scoring(0.9))).status_code == 200
    assert (await _patch(cell_id, _scoring(0.8))).status_code == 429

    clock.advance(60)
    assert (await _patch(cell_id, _scoring(0.7))).status_code == 200


@pytest.mark.asyncio
async def test_a_caller_without_write_access_learns_nothing_about_the_budget():
    """Access is decided first, so a stranger cannot probe the limit."""
    _install_app(ScoringPatchLimit(max_patches=1, window_seconds=3600))
    import amp_server.main as main_mod

    cell = make_cell(owner_id="user-someone-else", created_by="agent-someone-else")
    await main_mod.get_storage().save(cell)

    response = await _patch(cell.id, _scoring(0.9))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ACCESS_DENIED"


@pytest.mark.asyncio
async def test_deleting_a_cell_forgets_its_budget():
    _install_app(ScoringPatchLimit(max_patches=1, window_seconds=3600))
    import amp_server.main as main_mod

    cell = make_cell(
        owner_id=_AGENT, created_by=_AGENT, status=LifecycleStatus.ARCHIVED
    )
    await main_mod.get_storage().save(cell)
    assert (await _patch(cell.id, _scoring(0.9))).status_code == 200

    async with await _client() as client:
        deleted = await client.delete(f"/amp/v1/memories/{cell.id}", headers=_headers())

    assert deleted.status_code == 204
    assert main_mod._scoring_limiter.tracked_cells() == 0


@pytest.mark.asyncio
async def test_spec_advertises_the_budget_it_enforces():
    _install_app(ScoringPatchLimit(max_patches=2, window_seconds=900))
    cell_id = await _store_cell()

    async with await _client() as client:
        advertised = (await client.get("/amp/v1/spec")).json()["capabilities"][
            "scoring_patch_limit"
        ]

    assert advertised == {"max_patches": 2, "window_seconds": 900}

    # And the advertised number is the one the route uses.
    assert (await _patch(cell_id, _scoring(0.9))).status_code == 200
    assert (await _patch(cell_id, _scoring(0.8))).status_code == 200
    assert (await _patch(cell_id, _scoring(0.7))).status_code == 429


@pytest.mark.asyncio
async def test_spec_says_null_when_the_limit_is_off():
    _install_app(ScoringPatchLimit(max_patches=0))
    cell_id = await _store_cell()

    async with await _client() as client:
        advertised = (await client.get("/amp/v1/spec")).json()["capabilities"][
            "scoring_patch_limit"
        ]

    assert advertised is None
    for _ in range(10):
        assert (await _patch(cell_id, _scoring(0.9))).status_code == 200
