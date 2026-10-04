"""AMP MCP Server — wrapper module exposing AMP capabilities to MCP clients."""

from __future__ import annotations

import os
from datetime import UTC, datetime

from mcp.server.fastmcp import FastMCP

from amp_server.access_control import check_read_access, check_write_access
from amp_server.models import (
    LifecycleStatus,
    MemoryAccessPolicy,
    MemoryCell,
    MemoryContent,
    MemoryIdentity,
    MemoryLifecycle,
    MemoryScoring,
    MemoryType,
    OwnerType,
    SearchRequest,
)
from amp_server.storage.base import InvalidTransitionError, MemoryNotFoundError
from amp_server.storage.chroma import ChromaAdapter

# Create the FastMCP server instance
mcp = FastMCP("AMP")

#: The identity this MCP server acts as when `AMP_MCP_AGENT_ID` is unset.
DEFAULT_AGENT_ID = "mcp_client"


def agent_id() -> str:
    """Which agent this MCP server acts as.

    Every access rule is decided from this identity, so one shared default means
    every MCP client pointed at the same store is the same agent: a cell one of
    them created is readable by all of them, `readable_by` patterns naming real
    agent ids never match anything a caller wrote, and `identity.created_by` -
    the attribution RFC-AMP-001 §5 leans on to make a poisoned memory traceable -
    records a name no agent uses. A caller who passes `readable_by` to
    `amp_remember` is in the worst spot: the cell it just stored is one its own
    server may not be able to recall.

    Run one MCP server per agent and set `AMP_MCP_AGENT_ID` in its `mcp_config.json`
    `env` block. Read per call rather than cached at import, because the client
    sets the environment when it spawns this process.
    """
    return os.environ.get("AMP_MCP_AGENT_ID") or DEFAULT_AGENT_ID


# Storage injection holder for testing
_storage: ChromaAdapter | None = None


def set_storage(storage_instance: ChromaAdapter | None) -> None:
    """Inject a test storage instance."""
    global _storage
    _storage = storage_instance


def get_storage() -> ChromaAdapter:
    """Return the injected storage instance, or build a default one."""
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
            created_by=agent_id(),
        ),
        lifecycle=MemoryLifecycle(
            created_at=datetime.now(UTC),
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
    results = await storage.search(request, agent_id=agent_id())
    if not results:
        return "No memories found."

    lines = []
    for cell in results:
        lines.append(
            f"- [{cell.type.value}] {cell.content.text} "
            f"(created: {cell.lifecycle.created_at})"
        )
    return "\n".join(lines)


@mcp.tool()
async def amp_forget(memory_id: str, owner_id: str) -> str:
    """Archive and then mark_deleted the specified memory cell."""
    storage = get_storage()
    try:
        cell = await storage._get_raw(memory_id)
    except MemoryNotFoundError:
        return "Memory not found."

    if cell.identity.owner_id != owner_id:
        return "Memory not found."

    if not check_write_access(cell, agent_id()):
        return "Memory not found."

    try:
        # Step 1: Update status to archived
        await storage.update(
            memory_id, {"lifecycle": {"status": LifecycleStatus.ARCHIVED.value}}
        )
        # Step 2: Mark deleted
        await storage.mark_deleted(memory_id)
        return f"Memory {memory_id} forgotten."
    except (InvalidTransitionError, MemoryNotFoundError):
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

    allowed_cells = [c for c in cells if check_read_access(c, agent_id())]

    if not allowed_cells:
        return "No memories found."

    lines = []
    for cell in allowed_cells:
        lines.append(
            f"- [{cell.type.value}] {cell.content.text} "
            f"(created: {cell.lifecycle.created_at})"
        )
    return "\n".join(lines)


def main():
    """Run the FastMCP server in standard stdio mode."""
    mcp.run()


if __name__ == "__main__":
    main()
