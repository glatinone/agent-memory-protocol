"""Shared fixtures for AMP server tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from amp_server.models import (
    LifecycleStatus,
    MemoryAccessPolicy,
    MemoryCell,
    MemoryCellCreate,
    MemoryContent,
    MemoryIdentity,
    MemoryLifecycle,
    MemoryProvenance,
    MemoryScoring,
    MemoryType,
    OwnerType,
    SourceType,
    ExtractionMethod,
)
from amp_server.storage.chroma import ChromaAdapter


@pytest.fixture
def storage():
    """Fresh in-memory ChromaAdapter with a unique collection per test."""
    unique_name = f"test_{uuid.uuid4().hex[:12]}"
    return ChromaAdapter(collection_name=unique_name)


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
            created_at=created_at or datetime.now(timezone.utc),
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
