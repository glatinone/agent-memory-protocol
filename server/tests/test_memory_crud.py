"""Tests for StorageAdapter CRUD and HTTP memory endpoints."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from amp_server.models import (
    LifecycleStatus,
    MemoryContent,
    MemoryCellUpdate,
    MemoryScoring,
    MemoryType,
    SearchRequest,
)
from amp_server.storage.base import InvalidTransitionError, MemoryNotFoundError

from conftest import make_cell


# ---------------------------------------------------------------------------
# Save & Get
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_and_get(storage):
    cell = make_cell(text="Python is preferred")
    cell_id = await storage.save(cell)
    assert cell_id == cell.id

    retrieved = await storage.get(cell_id)
    assert retrieved.id == cell.id
    assert retrieved.content.text == "Python is preferred"
    assert retrieved.type == MemoryType.SEMANTIC


@pytest.mark.asyncio
async def test_get_increments_access_count(storage):
    cell = make_cell()
    await storage.save(cell)
    assert cell.scoring.access_count == 0

    retrieved = await storage.get(cell.id)
    assert retrieved.scoring.access_count == 1

    retrieved2 = await storage.get(cell.id)
    assert retrieved2.scoring.access_count == 2


@pytest.mark.asyncio
async def test_get_nonexistent_raises(storage):
    with pytest.raises(MemoryNotFoundError):
        await storage.get("nonexistent-id")


# ---------------------------------------------------------------------------
# Update (uses MemoryCellUpdate, not raw dict)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_content(storage):
    cell = make_cell(text="old text")
    await storage.save(cell)

    updated = await storage.update(
        cell.id, MemoryCellUpdate(content=MemoryContent(text="new text"))
    )
    assert updated.content.text == "new text"

    retrieved = await storage.get(cell.id)
    assert retrieved.content.text == "new text"


@pytest.mark.asyncio
async def test_update_scoring(storage):
    cell = make_cell(importance=0.5)
    await storage.save(cell)

    updated = await storage.update(
        cell.id, MemoryCellUpdate(scoring=MemoryScoring(importance=0.9))
    )
    assert updated.scoring.importance == 0.9


@pytest.mark.asyncio
async def test_update_nonexistent_raises(storage):
    with pytest.raises(MemoryNotFoundError):
        await storage.update(
            "nonexistent-id", MemoryCellUpdate(content=MemoryContent(text="nope"))
        )


# ---------------------------------------------------------------------------
# Delete — full lifecycle: archived → mark_deleted → purge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_deleted_and_purge(storage):
    """Archiving a cell, marking it deleted, then purging removes it from storage."""
    cell = make_cell(status=LifecycleStatus.ARCHIVED)
    await storage.save(cell)

    await storage.mark_deleted(cell.id)
    # Record still exists but status is deleted
    raw = await storage._get_raw(cell.id)
    assert raw.lifecycle.status == LifecycleStatus.DELETED

    await storage.purge(cell.id)
    # Record is now physically removed
    with pytest.raises(MemoryNotFoundError):
        await storage.get(cell.id)


@pytest.mark.asyncio
async def test_mark_deleted_non_archived_raises(storage):
    """mark_deleted on an active cell raises InvalidTransitionError."""
    cell = make_cell(status=LifecycleStatus.ACTIVE)
    await storage.save(cell)

    with pytest.raises(InvalidTransitionError):
        await storage.mark_deleted(cell.id)


@pytest.mark.asyncio
async def test_mark_deleted_nonexistent_raises(storage):
    with pytest.raises(MemoryNotFoundError):
        await storage.mark_deleted("nonexistent-id")


# ---------------------------------------------------------------------------
# Search (agent_id required for access control)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_by_owner(storage):
    cell1 = make_cell(owner_id="user-A", text="alpha preference")
    cell2 = make_cell(owner_id="user-B", text="beta preference")
    await storage.save(cell1)
    await storage.save(cell2)

    request = SearchRequest(query="preference", owner_id="user-A")
    results = await storage.search(request, agent_id="agent-456")
    assert len(results) >= 1
    assert all(r.identity.owner_id == "user-A" for r in results)


@pytest.mark.asyncio
async def test_search_filters_by_type(storage):
    cell1 = make_cell(memory_type=MemoryType.SEMANTIC, text="semantic fact")
    cell2 = make_cell(memory_type=MemoryType.EPISODIC, text="episodic event")
    await storage.save(cell1)
    await storage.save(cell2)

    request = SearchRequest(
        query="fact",
        owner_id="user-123",
        types=[MemoryType.SEMANTIC],
    )
    results = await storage.search(request, agent_id="agent-456")
    assert all(r.type == MemoryType.SEMANTIC for r in results)


@pytest.mark.asyncio
async def test_search_filters_stale(storage):
    active = make_cell(text="active memory", status=LifecycleStatus.ACTIVE)
    stale = make_cell(text="stale memory", status=LifecycleStatus.STALE)
    await storage.save(active)
    await storage.save(stale)

    request = SearchRequest(query="memory", owner_id="user-123", include_stale=False)
    results = await storage.search(request, agent_id="agent-456")
    assert all(r.lifecycle.status == LifecycleStatus.ACTIVE for r in results)


@pytest.mark.asyncio
async def test_search_empty_store(storage):
    request = SearchRequest(query="anything", owner_id="user-123")
    results = await storage.search(request, agent_id="agent-456")
    assert results == []


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_all(storage):
    cell1 = make_cell(text="one")
    cell2 = make_cell(text="two")
    await storage.save(cell1)
    await storage.save(cell2)

    all_cells = await storage.list_all()
    assert len(all_cells) == 2


@pytest.mark.asyncio
async def test_list_by_owner(storage):
    cell1 = make_cell(owner_id="owner-A", text="A's memory")
    cell2 = make_cell(owner_id="owner-B", text="B's memory")
    await storage.save(cell1)
    await storage.save(cell2)

    a_cells = await storage.list_by_owner("owner-A")
    assert len(a_cells) == 1
    assert a_cells[0].identity.owner_id == "owner-A"


# ---------------------------------------------------------------------------
# HTTP endpoint tests (spec §9.2)
# ---------------------------------------------------------------------------

_AGENT = "agent_test"
_HEADERS = {"X-AMP-Agent-ID": _AGENT}


def _minimal_body(text: str = "test memory") -> dict:
    return {
        "type": "semantic",
        "content": {"text": text},
        "identity": {"owner_id": "user_1", "owner_type": "user"},
    }


@pytest.mark.asyncio
async def test_create_memory_returns_201_with_mem_prefixed_id():
    """POST /memories returns 201 and the server-assigned id starts with 'mem_'."""
    from amp_server.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/amp/v1/memories", headers=_HEADERS, json=_minimal_body()
        )

    assert resp.status_code == 201
    assert resp.json()["id"].startswith("mem_")


@pytest.mark.asyncio
async def test_create_memory_missing_must_field_returns_422():
    """POST with missing MUST fields returns 422."""
    from amp_server.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/amp/v1/memories",
            headers=_HEADERS,
            json={"type": "semantic"},  # missing content and identity
        )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_get_memory_increments_access_count():
    """GET increments access_count on each successful read."""
    from amp_server.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        create = await client.post(
            "/amp/v1/memories",
            headers=_HEADERS,
            json=_minimal_body("access count test"),
        )
        assert create.status_code == 201
        memory_id = create.json()["id"]

        get1 = await client.get(f"/amp/v1/memories/{memory_id}", headers=_HEADERS)
        get2 = await client.get(f"/amp/v1/memories/{memory_id}", headers=_HEADERS)

    assert get1.status_code == 200
    assert get2.status_code == 200
    assert get2.json()["scoring"]["access_count"] == 2


@pytest.mark.asyncio
async def test_get_without_agent_id_header_returns_401():
    """GET without X-AMP-Agent-ID returns 401 MISSING_AGENT_ID."""
    from amp_server.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/amp/v1/memories/mem_anything")

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "MISSING_AGENT_ID"


@pytest.mark.asyncio
async def test_delete_non_archived_cell_returns_409():
    """DELETE on an active cell returns 409 INVALID_TRANSITION."""
    from amp_server.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        create = await client.post(
            "/amp/v1/memories",
            headers=_HEADERS,
            json=_minimal_body("to be deleted"),
        )
        assert create.status_code == 201
        memory_id = create.json()["id"]

        delete = await client.delete(
            f"/amp/v1/memories/{memory_id}", headers=_HEADERS
        )

    assert delete.status_code == 409
    assert delete.json()["error"]["code"] == "INVALID_TRANSITION"


@pytest.mark.asyncio
async def test_delete_by_non_creator_returns_403():
    """DELETE by an agent that is not the creator returns 403 ACCESS_DENIED."""
    from amp_server.main import app

    creator_headers = {"X-AMP-Agent-ID": "agent_creator"}
    intruder_headers = {"X-AMP-Agent-ID": "agent_intruder"}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        create = await client.post(
            "/amp/v1/memories",
            headers=creator_headers,
            json=_minimal_body("protected memory"),
        )
        assert create.status_code == 201
        memory_id = create.json()["id"]

        delete = await client.delete(
            f"/amp/v1/memories/{memory_id}", headers=intruder_headers
        )

    assert delete.status_code == 403
    assert delete.json()["error"]["code"] == "ACCESS_DENIED"
