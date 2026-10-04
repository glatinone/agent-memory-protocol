"""Abstract StorageAdapter — interface for all storage backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from amp_server.models import (
    LifecycleStatus,
    MemoryCell,
    MemoryCellUpdate,
    MemoryType,
    SearchRequest,
)
from amp_server.retention import RETENTION_DAYS


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
    """Persistence for memory cells.

    Implementations enforce the server's advertised cell size limit
    (`amp_server.limits.MAX_CELL_SIZE_BYTES`) in `save` and `update`, before
    writing, so a refused cell leaves no trace and `GET /spec` stays true.
    """

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

        Only valid when status is 'deleted' — raises InvalidTransitionError
        otherwise. Refused inside the GDPR retention window with
        `RetentionWindowError`: the window is enforced here, not left to the
        caller, because the spec makes retention the server's responsibility and
        a caller who purges too early destroys the audit evidence the window
        exists to protect."""

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
        offset: int = 0,
    ) -> list[MemoryCell]:
        """Filter MemoryCells by structured criteria without semantic search.

        `limit` and `offset` window the *filtered* result, so a caller can page
        through it. They count cells matching the criteria, not cells examined,
        and every backend must window the same way or a page means something
        different depending on where the data lives.
        """

    @abstractmethod
    async def list_by_owner(self, owner_id: str) -> list[MemoryCell]:
        """Return all MemoryCells owned by the given owner_id."""

    @abstractmethod
    async def _get_raw(self, memory_id: str) -> MemoryCell:
        """Return a cell without applying the access boost.

        Internal, but part of the contract: the API layer uses it to decide
        whether a cell exists without touching `access_count` or
        `last_accessed_at`, which is what makes the "403 whether it exists or
        not" rule in spec §8.4 work. `spec/v0.1.0/lifecycle.md` §5 names it
        `_get_raw`, so the name is kept.

        Raises MemoryNotFoundError if the cell is missing.
        """

    @property
    def name(self) -> str:
        """Short identifier reported at GET /spec under `storage_backends`.

        Derived from the class name so added adapters are reported by default
        rather than silently missing from the capability they are part of.
        """
        return type(self).__name__.removesuffix("Adapter").lower()

    def close(self) -> None:
        """Release any held resources. The lifespan calls this on shutdown."""
        return None

    @property
    def retention_days(self) -> int:
        """How long a deleted cell is held before it may be purged.

        Reported by `GET /spec` and read by the retention pass, so both agree on
        one number. The default is the spec's floor; an adapter may hold cells
        longer, and the check inside `purge` is what actually decides.
        """
        return RETENTION_DAYS

    @property
    def embedding(self) -> dict[str, Any] | None:
        """What embeds text for this backend, reported by `GET /spec`.

        An adapter that owns both storage and retrieval knows which embedding
        model its vectors came from, and that is the answer `/spec` needs. None
        means the backend has no embeddings of its own.
        """
        return None

    @abstractmethod
    async def list_all(self) -> list[MemoryCell]:
        """Return all MemoryCells in storage. Used by LifecycleEngine."""
