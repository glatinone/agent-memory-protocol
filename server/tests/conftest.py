"""Shared fixtures for AMP server tests."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

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
