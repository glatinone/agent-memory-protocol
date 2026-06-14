"""Unit tests for AMP MCP server tools."""

from __future__ import annotations

from datetime import datetime, timezone
import pytest

from amp_server.models import LifecycleStatus, MemoryType
from amp_server.mcp_server import (
    set_storage,
    amp_remember,
    amp_recall,
    amp_forget,
    amp_list_memories,
)
from conftest import make_cell


@pytest.fixture(autouse=True)
def setup_mcp_storage(storage):
    """Automatically inject the test's fresh ChromaAdapter into mcp_server."""
    set_storage(storage)
    yield
    set_storage(None)


@pytest.mark.asyncio
async def test_amp_remember_success(storage):
    # Call the tool
    result = await amp_remember(
        content="User loves programming in Python",
        owner_id="user-123",
        type="semantic",
        importance=0.8,
        readable_by=["agent-789"],
    )

    # Verify return message
    assert result.startswith("Memory stored: mem_")
    memory_id = result.split(": ")[1]

    # Fetch from storage to verify creation
    cell = await storage._get_raw(memory_id)
    assert cell.type == MemoryType.SEMANTIC
    assert cell.content.text == "User loves programming in Python"
    assert cell.identity.owner_id == "user-123"
    assert cell.identity.created_by == "mcp_client"
    assert cell.scoring.importance == 0.8
    assert "agent-789" in cell.access_policy.readable_by


@pytest.mark.asyncio
async def test_amp_recall_success(storage):
    # Setup some test cells in storage
    cell1 = make_cell(
        owner_id="user-123",
        created_by="mcp_client",
        text="Target python preference",
        memory_type=MemoryType.SEMANTIC,
    )
    cell2 = make_cell(
        owner_id="user-123",
        created_by="mcp_client",
        text="User hates eating bananas",
        memory_type=MemoryType.SEMANTIC,
    )
    cell_other = make_cell(
        owner_id="user-456",
        created_by="mcp_client",
        text="Target other user python preference",
        memory_type=MemoryType.SEMANTIC,
    )
    await storage.save(cell1)
    await storage.save(cell2)
    await storage.save(cell_other)

    # Call amp_recall for user-123 with limit=1 to fetch only the closest match
    result = await amp_recall(query="python", owner_id="user-123", limit=1)
    assert "Target python preference" in result
    assert "User hates eating bananas" not in result
    assert "Target other user" not in result
    assert result.startswith("- [semantic]")

    # Call amp_recall where no matches exist for the owner
    result_empty = await amp_recall(query="python", owner_id="user-empty")
    assert result_empty == "No memories found."


@pytest.mark.asyncio
async def test_amp_forget_success(storage):
    # Create cell to forget
    cell = make_cell(
        owner_id="user-123",
        created_by="mcp_client",
        text="Forgot this text",
    )
    await storage.save(cell)

    # Perform amp_forget
    res = await amp_forget(memory_id=cell.id, owner_id="user-123")
    assert res == f"Memory {cell.id} forgotten."

    # Verify status in storage is DELETED
    updated_cell = await storage._get_raw(cell.id)
    assert updated_cell.lifecycle.status == LifecycleStatus.DELETED


@pytest.mark.asyncio
async def test_amp_forget_non_existent(storage):
    res = await amp_forget(memory_id="mem_nonexistent123", owner_id="user-123")
    assert res == "Memory not found."


@pytest.mark.asyncio
async def test_amp_forget_unauthorized_owner(storage):
    cell = make_cell(
        owner_id="user-123",
        created_by="mcp_client",
        text="Some secret text",
    )
    await storage.save(cell)

    # Try to forget with wrong owner_id
    res = await amp_forget(memory_id=cell.id, owner_id="user-456")
    assert res == "Memory not found."

    # Verify it is still active
    cell_after = await storage._get_raw(cell.id)
    assert cell_after.lifecycle.status == LifecycleStatus.ACTIVE


@pytest.mark.asyncio
async def test_amp_list_memories_success(storage):
    cell1 = make_cell(
        owner_id="user-123",
        created_by="mcp_client",
        text="First active memory",
        memory_type=MemoryType.EPISODIC,
    )
    cell2 = make_cell(
        owner_id="user-123",
        created_by="mcp_client",
        text="Second active memory",
        memory_type=MemoryType.SEMANTIC,
    )
    cell_deleted = make_cell(
        owner_id="user-123",
        created_by="mcp_client",
        text="Deleted memory",
        status=LifecycleStatus.DELETED,
    )
    await storage.save(cell1)
    await storage.save(cell2)
    await storage.save(cell_deleted)

    # List all active memories
    res = await amp_list_memories(owner_id="user-123")
    assert "First active memory" in res
    assert "Second active memory" in res
    assert "Deleted memory" not in res
    assert "- [episodic]" in res
    assert "- [semantic]" in res

    # List with type filter
    res_episodic = await amp_list_memories(owner_id="user-123", type="episodic")
    assert "First active memory" in res_episodic
    assert "Second active memory" not in res_episodic

    # List with no matches
    res_empty = await amp_list_memories(owner_id="user-456")
    assert res_empty == "No memories found."
