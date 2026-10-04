"""Shared fixtures for AMP server tests."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from amp_server.models import (
    ExtractionMethod,
    LifecycleStatus,
    MemoryAccessPolicy,
    MemoryCell,
    MemoryContent,
    MemoryIdentity,
    MemoryLifecycle,
    MemoryProvenance,
    MemoryScoring,
    MemoryType,
    OwnerType,
    SourceType,
)
from amp_server.retention import RETENTION_DAYS
from amp_server.storage.chroma import ChromaAdapter


@pytest.fixture
def storage():
    """Fresh in-memory ChromaAdapter with a unique collection per test."""
    unique_name = f"test_{uuid.uuid4().hex[:12]}"
    return ChromaAdapter(collection_name=unique_name)


# --- Postgres ---------------------------------------------------------------
#
# These tests need a live server with the pgvector extension. Locally they skip
# when AMP_TEST_POSTGRES_DSN is unset; CI sets it from a service container and
# also sets AMP_REQUIRE_POSTGRES, which turns the skip into a failure. That flag
# exists because a suite that skips itself still reports green, and the whole
# point of the job is to prove the adapter works against a real database.

POSTGRES_DSN = os.environ.get("AMP_TEST_POSTGRES_DSN")
POSTGRES_REQUIRED = os.environ.get("AMP_REQUIRE_POSTGRES") not in (
    None,
    "",
    "0",
    "false",
)


def postgres_or_skip() -> str:
    """The DSN, or skip - unless this run is one where skipping is not allowed."""
    if POSTGRES_DSN:
        return POSTGRES_DSN
    if POSTGRES_REQUIRED:
        pytest.fail(
            "AMP_REQUIRE_POSTGRES is set but AMP_TEST_POSTGRES_DSN is not: "
            "the postgres adapter would not have been exercised"
        )
    pytest.skip("set AMP_TEST_POSTGRES_DSN to run the postgres adapter tests")


@pytest.fixture
def postgres_storage():
    """A PostgresAdapter on its own table, dropped afterwards."""
    from amp_server.storage.postgres import PostgresAdapter

    table = f"amp_test_{uuid.uuid4().hex[:12]}"
    adapter = PostgresAdapter(dsn=postgres_or_skip(), table=table)
    yield adapter
    with adapter._connection.cursor() as cursor:
        cursor.execute(f"DROP TABLE IF EXISTS {table}")
    adapter.close()


def make_cell(
    *,
    owner_id: str = "user-123",
    created_by: str = "agent-456",
    memory_type: MemoryType = MemoryType.SEMANTIC,
    text: str = "User prefers email communication",
    status: LifecycleStatus = LifecycleStatus.ACTIVE,
    importance: float = 0.5,
    confidence: float = 1.0,
    decay_rate: float = 0.01,
    readable_by: list[str] | None = None,
    writable_by: list[str] | None = None,
    public: bool = False,
    created_at: datetime | None = None,
) -> MemoryCell:
    """Helper to build a MemoryCell with sensible defaults."""
    return MemoryCell(
        type=memory_type,
        content=MemoryContent(text=text),
        identity=MemoryIdentity(
            owner_id=owner_id,
            owner_type=OwnerType.USER,
            created_by=created_by,
        ),
        lifecycle=MemoryLifecycle(
            created_at=created_at or datetime.now(UTC),
            status=status,
        ),
        scoring=MemoryScoring(
            importance=importance,
            confidence=confidence,
            decay_rate=decay_rate,
        ),
        access_policy=MemoryAccessPolicy(
            readable_by=readable_by or [],
            writable_by=writable_by or [],
            public=public,
        ),
        provenance=MemoryProvenance(
            source_type=SourceType.CONVERSATION,
            extraction_method=ExtractionMethod.LLM_EXTRACTION,
        ),
    )


# --- The HTTP app -----------------------------------------------------------
#
# Every test file that talks to the HTTP app needs the app pointed at state the
# test owns, because `get_storage()` reads a module global that the lifespan sets
# when a real server boots. Each file used to install that itself - five slightly
# different copies - and a file that forgot reached whatever state a *previous
# file* had left behind. That held while the whole suite ran in one process and
# broke the moment a single file was run, which is how anyone runs it while
# working. One helper, in conftest, so a file cannot get it subtly differently and
# cannot silently inherit somebody else's.


def install_app_state(
    *,
    api_key_store=None,
    scoring_limit=None,
    scoring_clock=None,
    lifecycle_settings=None,
    retention_days: int = RETENTION_DAYS,
):
    """Point the app at fresh state the way the lifespan would.

    Returns the objects it installed, so a test can assert against the same
    storage or limiter the app is using rather than a second copy.
    """
    import amp_server.main as main_mod
    from amp_server.lifecycle import LifecycleEngine
    from amp_server.ratelimit import ScoringPatchLimit, ScoringPatchLimiter

    storage = ChromaAdapter(
        collection_name=f"test_{uuid.uuid4().hex[:12]}",
        retention_days=retention_days,
    )
    limit = scoring_limit or ScoringPatchLimit()
    limiter = ScoringPatchLimiter(
        limit, **({"clock": scoring_clock} if scoring_clock else {})
    )

    main_mod._storage = storage
    main_mod._lifecycle = LifecycleEngine(storage)
    main_mod._api_key_store = api_key_store
    main_mod._scoring_limit = limit
    main_mod._scoring_limiter = limiter
    if lifecycle_settings is not None:
        main_mod._lifecycle_settings = lifecycle_settings

    return SimpleNamespace(storage=storage, limiter=limiter, scoring_limit=limit)


@pytest.fixture
def app_state():
    """Fresh app state for one test."""
    return install_app_state()


@pytest.fixture
async def app_client(app_state):
    """An AsyncClient over the app, on state this test owns."""
    from httpx import ASGITransport, AsyncClient

    import amp_server.main as main_mod

    async with AsyncClient(
        transport=ASGITransport(app=main_mod.app), base_url="http://test"
    ) as client:
        yield client


def make_create_body(
    *,
    owner_id: str = "user-123",
    created_by: str = "agent-456",
    memory_type: str = "semantic",
    text: str = "User prefers email communication",
) -> dict:
    """Helper to build a POST body dict for creating memories via API."""
    return {
        "type": memory_type,
        "content": {"text": text},
        "identity": {
            "owner_id": owner_id,
            "owner_type": "user",
            "created_by": created_by,
        },
    }
