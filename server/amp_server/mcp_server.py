"""AMP MCP Server — wrapper module exposing AMP capabilities to MCP clients."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from mcp.server.fastmcp import FastMCP

from amp_server.models import (
    MemoryCell,
    MemoryType,
    MemoryContent,
    MemoryIdentity,
    MemoryLifecycle,
    MemoryScoring,
    MemoryAccessPolicy,
    OwnerType,
    LifecycleStatus,
    SearchRequest,
)
from amp_server.storage.chroma import ChromaAdapter
from amp_server.access_control import check_read_access, check_write_access

# Create the FastMCP server instance
mcp = FastMCP("AMP")

# Storage injection holder for testing
_storage: ChromaAdapter | None = None


def set_storage(storage_instance: ChromaAdapter | None) -> None:
    """Inject a test storage instance."""
    global _storage
    _storage = storage_instance


def get_storage() -> ChromaAdapter:
    """Retrieve the storage instance (either injected or default persistent/ephemeral)."""
    global _storage
    if _storage is None:
        persist_dir = os.environ.get("AMP_PERSIST_DIR")
        _storage = ChromaAdapter(persist_directory=persist_dir)
    return _storage


@mcp.tool()
async def amp_remember(
    content: str,
    owner_id: str,
    type: str = "semantic",
    importance: float = 0.5,
    readable_by: list[str] | None = None,
) -> str:
    """Remember a piece of information (create a memory cell)."""
    storage = get_storage()
    cell = MemoryCell(
        type=MemoryType(type),
        content=MemoryContent(text=content),
        identity=MemoryIdentity(
            owner_id=owner_id,
            owner_type=OwnerType.USER,
            created_by="mcp_client",
        ),
        lifecycle=MemoryLifecycle(
            created_at=datetime.now(timezone.utc),
            status=LifecycleStatus.ACTIVE,
        ),
        scoring=MemoryScoring(importance=importance),
        access_policy=MemoryAccessPolicy(readable_by=readable_by or []),
    )
    memory_id = await storage.save(cell)
    return f"Memory stored: {memory_id}"


@mcp.tool()
async def amp_recall(
    query: str,
    owner_id: str,
    limit: int = 5,
    include_stale: bool = False,
) -> str:
    """Search and recall memories matching the query."""
    storage = get_storage()
    request = SearchRequest(
        query=query,
        owner_id=owner_id,
        limit=limit,
        include_stale=include_stale,
    )
    results = await storage.search(request, agent_id="mcp_client")
    if not results:
        return "No memories found."

    lines = []
    for cell in results:
        lines.append(f"- [{cell.type.value}] {cell.content.text} (created: {cell.lifecycle.created_at})")
    return "\n".join(lines)


@mcp.tool()
async def amp_forget(memory_id: str, owner_id: str) -> str:
    """Archive and then mark_deleted the specified memory cell."""
    storage = get_storage()
    try:
        cell = await storage._get_raw(memory_id)
    except Exception:
        return "Memory not found."

    if cell.identity.owner_id != owner_id:
        return "Memory not found."

    if not check_write_access(cell, "mcp_client"):
        return "Memory not found."

    try:
        # Step 1: Update status to archived
        await storage.update(memory_id, {"lifecycle": {"status": LifecycleStatus.ARCHIVED.value}})
        # Step 2: Mark deleted
        await storage.mark_deleted(memory_id)
        return f"Memory {memory_id} forgotten."
    except Exception:
        return "Memory not found."


@mcp.tool()
async def amp_list_memories(
    owner_id: str,
    type: str | None = None,
    limit: int = 20,
) -> str:
    """List all active memories for the specified owner."""
    storage = get_storage()
    types_list = [MemoryType(type)] if type else None

    cells = await storage.query(
        owner_id=owner_id,
        types=types_list,
        status=[LifecycleStatus.ACTIVE],
        limit=limit,
    )

    allowed_cells = [c for c in cells if check_read_access(c, "mcp_client")]

    if not allowed_cells:
        return "No memories found."

    lines = []
    for cell in allowed_cells:
        lines.append(f"- [{cell.type.value}] {cell.content.text} (created: {cell.lifecycle.created_at})")
    return "\n".join(lines)


def main():
    """Run the FastMCP server in standard stdio mode."""
    mcp.run()


if __name__ == "__main__":
    main()
