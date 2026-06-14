"""Abstract StorageAdapter — interface for all storage backends."""

from __future__ import annotations

from abc import ABC, abstractmethod

from amp_server.models import (
    LifecycleStatus,
    MemoryCell,
    MemoryCellUpdate,
    MemoryType,
    SearchRequest,
)


class MemoryNotFoundError(Exception):
    """Raised when a memory cell is not found in storage."""

    def __init__(self, memory_id: str) -> None:
        self.memory_id = memory_id
        super().__init__(f"Memory cell not found: {memory_id}")


class InvalidTransitionError(Exception):
    """Raised when a requested lifecycle transition is not valid per spec §6.1."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class StorageAdapter(ABC):

    @abstractmethod
    async def save(self, cell: MemoryCell) -> str:
        """Persist a MemoryCell and return its id."""

    @abstractmethod
    async def get(self, memory_id: str) -> MemoryCell:
        """Return a MemoryCell by id, updating access_count and last_accessed_at.
        Raises MemoryNotFoundError if missing."""

    @abstractmethod
    async def update(self, memory_id: str, updates: MemoryCellUpdate) -> MemoryCell:
        """Apply partial updates to a MemoryCell and return the updated cell.
        MUST NOT modify id, type, amp_version, or identity fields.
        Raises MemoryNotFoundError if the cell does not exist."""

    @abstractmethod
    async def mark_deleted(self, memory_id: str) -> None:
        """Transition a MemoryCell status to 'deleted'. Does NOT remove physical data.
        Per spec §6.3: underlying data is retained for 30 days for GDPR audit window.
        Only valid from 'archived' status — raises InvalidTransitionError otherwise."""

    @abstractmethod
    async def purge(self, memory_id: str) -> None:
        """Physically remove a MemoryCell from storage.
        Only valid when status is 'deleted' — raises InvalidTransitionError otherwise.
        Call only after the 30-day GDPR retention window has elapsed."""

    @abstractmethod
    async def search(self, request: SearchRequest, agent_id: str) -> list[MemoryCell]:
        """Semantic search for MemoryCells matching the request criteria,
        filtered to cells the given agent_id is authorized to read."""

    @abstractmethod
    async def query(
        self,
        owner_id: str | None,
        types: list[MemoryType] | None,
        status: list[LifecycleStatus] | None,
        limit: int,
    ) -> list[MemoryCell]:
        """Filter MemoryCells by structured criteria without semantic search."""

    @abstractmethod
    async def list_by_owner(self, owner_id: str) -> list[MemoryCell]:
        """Return all MemoryCells owned by the given owner_id."""

    @abstractmethod
    async def list_all(self) -> list[MemoryCell]:
        """Return all MemoryCells in storage. Used by LifecycleEngine."""
