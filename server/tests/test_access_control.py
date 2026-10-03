"""Tests for access control — permission enforcement."""

from __future__ import annotations

import pytest
from conftest import make_cell

from amp_server.access_control import (
    AccessDeniedError,
    check_read_access,
    check_write_access,
    enforce_read,
    enforce_write,
)
from amp_server.models import SearchRequest

# ---------------------------------------------------------------------------
# Read access
# ---------------------------------------------------------------------------


def test_creator_can_always_read():
    cell = make_cell(created_by="agent-A", readable_by=["agent-B"])
    assert check_read_access(cell, "agent-A") is True


def test_owner_can_always_read():
    cell = make_cell(owner_id="user-X", readable_by=["agent-B"])
    assert check_read_access(cell, "user-X") is True


def test_agent_in_readable_by_can_read():
    cell = make_cell(readable_by=["agent-C"])
    assert check_read_access(cell, "agent-C") is True


def test_agent_not_in_readable_by_cannot_read():
    cell = make_cell(readable_by=["agent-C"])
    assert check_read_access(cell, "agent-D") is False


def test_public_cell_readable_by_anyone():
    cell = make_cell(public=True, readable_by=[])
    assert check_read_access(cell, "random-agent") is True


def test_wildcard_read_pattern():
    """Wildcard in readable_by: 'agent_service_*' matches 'agent_service_v1'."""
    cell = make_cell(readable_by=["agent_service_*"])
    assert check_read_access(cell, "agent_service_v1") is True
    assert check_read_access(cell, "agent_billing_v1") is False


def test_default_policy_read():
    """No readable_by or writable_by → only owner and creator can read."""
    cell = make_cell(
        owner_id="user-X",
        created_by="agent-A",
        readable_by=[],
        writable_by=[],
    )
    assert check_read_access(cell, "user-X") is True
    assert check_read_access(cell, "agent-A") is True
    assert check_read_access(cell, "agent-B") is False


# ---------------------------------------------------------------------------
# Write access
# ---------------------------------------------------------------------------


def test_creator_can_always_write():
    cell = make_cell(created_by="agent-A", writable_by=["agent-B"])
    assert check_write_access(cell, "agent-A") is True


def test_owner_can_always_write():
    cell = make_cell(owner_id="user-X", writable_by=["agent-B"])
    assert check_write_access(cell, "user-X") is True


def test_agent_in_writable_by_can_write():
    cell = make_cell(writable_by=["agent-C"])
    assert check_write_access(cell, "agent-C") is True


def test_agent_not_in_writable_by_cannot_write():
    cell = make_cell(writable_by=["agent-C"])
    assert check_write_access(cell, "agent-D") is False


def test_wildcard_write_pattern():
    """Wildcard in writable_by works the same as readable_by."""
    cell = make_cell(writable_by=["agent_*"])
    assert check_write_access(cell, "agent_v1") is True
    assert check_write_access(cell, "billing_v1") is False


def test_default_policy_write():
    """No writable_by → only owner and creator can write."""
    cell = make_cell(
        owner_id="user-X",
        created_by="agent-A",
        readable_by=[],
        writable_by=[],
    )
    assert check_write_access(cell, "user-X") is True
    assert check_write_access(cell, "agent-A") is True
    assert check_write_access(cell, "agent-B") is False


# ---------------------------------------------------------------------------
# enforce_ functions
# ---------------------------------------------------------------------------


def test_enforce_read_passes():
    cell = make_cell(public=True)
    enforce_read(cell, "anyone")


def test_enforce_read_raises():
    cell = make_cell(readable_by=["agent-A"])
    with pytest.raises(AccessDeniedError):
        enforce_read(cell, "agent-B")


def test_enforce_write_passes():
    cell = make_cell(created_by="agent-A")
    enforce_write(cell, "agent-A")


def test_enforce_write_raises():
    cell = make_cell(writable_by=["agent-A"])
    with pytest.raises(AccessDeniedError):
        enforce_write(cell, "agent-B")


# ---------------------------------------------------------------------------
# HTTP integration (access control via API)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_get_returns_403_for_unauthorized_agent():
    """GET with X-AMP-Agent-ID that lacks read permission returns 403."""
    import uuid

    from httpx import ASGITransport, AsyncClient

    import amp_server.main as main_mod
    from amp_server.lifecycle import LifecycleEngine
    from amp_server.storage.chroma import ChromaAdapter

    main_mod._storage = ChromaAdapter(collection_name=f"test_{uuid.uuid4().hex[:12]}")
    main_mod._lifecycle = LifecycleEngine(main_mod._storage)

    async with AsyncClient(
        transport=ASGITransport(app=main_mod.app), base_url="http://test"
    ) as client:
        create_resp = await client.post(
            "/amp/v1/memories",
            json={
                "type": "semantic",
                "content": {"text": "secret memory"},
                "identity": {
                    "owner_id": "user-X",
                    "owner_type": "user",
                    "created_by": "agent-A",
                },
                "access_policy": {
                    "readable_by": ["agent-A"],
                    "writable_by": ["agent-A"],
                    "public": False,
                },
            },
        )
        assert create_resp.status_code == 201
        memory_id = create_resp.json()["id"]

        get_resp = await client.get(
            f"/amp/v1/memories/{memory_id}",
            headers={"X-AMP-Agent-ID": "agent-UNAUTHORIZED"},
        )
        assert get_resp.status_code == 403


@pytest.mark.asyncio
async def test_api_delete_returns_403_for_unauthorized_agent():
    """DELETE with unauthorized agent returns 403."""
    import uuid

    from httpx import ASGITransport, AsyncClient

    import amp_server.main as main_mod
    from amp_server.lifecycle import LifecycleEngine
    from amp_server.storage.chroma import ChromaAdapter

    main_mod._storage = ChromaAdapter(collection_name=f"test_{uuid.uuid4().hex[:12]}")
    main_mod._lifecycle = LifecycleEngine(main_mod._storage)

    async with AsyncClient(
        transport=ASGITransport(app=main_mod.app), base_url="http://test"
    ) as client:
        create_resp = await client.post(
            "/amp/v1/memories",
            json={
                "type": "semantic",
                "content": {"text": "protected memory"},
                "identity": {
                    "owner_id": "user-X",
                    "owner_type": "user",
                    "created_by": "agent-A",
                },
                "access_policy": {
                    "readable_by": ["agent-A"],
                    "writable_by": ["agent-A"],
                    "public": False,
                },
            },
        )
        assert create_resp.status_code == 201
        memory_id = create_resp.json()["id"]

        del_resp = await client.delete(
            f"/amp/v1/memories/{memory_id}",
            headers={"X-AMP-Agent-ID": "agent-UNAUTHORIZED"},
        )
        assert del_resp.status_code == 403


# ---------------------------------------------------------------------------
# Cross-surface agreement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_applies_the_same_read_rule_as_check_read_access(storage):
    """search() and the REST/MCP endpoints must agree on every agent.

    They did not: storage/chroma.py carried its own copy of the read rule that
    skipped any readable_by entry equal to the literal string "owner", while
    access_control.check_read_access matched it like any other pattern. An
    agent whose id is "owner" was therefore readable through GET but missing
    from search results. Run the whole matrix so the two cannot drift again.
    """
    cell = make_cell(
        owner_id="user-X",
        created_by="agent-A",
        readable_by=["agent_service_*", "owner"],
        text="wildcard readable memory",
    )
    await storage.save(cell)

    for agent in (
        "user-X",  # owner
        "agent-A",  # creator
        "agent_service_v1",  # matches the wildcard
        "owner",  # the literal that used to be filtered out
        "agent_other",  # matched by nothing
    ):
        request = SearchRequest(
            query="wildcard readable memory", owner_id="user-X", limit=10
        )
        results = await storage.search(request, agent_id=agent)
        found_in_search = any(c.id == cell.id for c in results)
        assert found_in_search == check_read_access(cell, agent), (
            f"search() and check_read_access() disagree for agent {agent!r}"
        )


@pytest.mark.asyncio
async def test_search_hides_a_cell_from_an_unrelated_agent(storage):
    """The agreement above must not be satisfied by letting everyone through."""
    cell = make_cell(
        owner_id="user-X",
        created_by="agent-A",
        readable_by=["agent_service_*"],
        text="restricted memory",
    )
    await storage.save(cell)

    request = SearchRequest(query="restricted memory", owner_id="user-X", limit=10)
    results = await storage.search(request, agent_id="agent_intruder")
    assert results == []


@pytest.mark.asyncio
async def test_public_cell_is_returned_by_search_for_any_agent(storage):
    cell = make_cell(public=True, readable_by=[], text="public memory")
    await storage.save(cell)

    request = SearchRequest(query="public memory", owner_id="user-123", limit=10)
    results = await storage.search(request, agent_id="agent_anyone")
    assert [c.id for c in results] == [cell.id]
