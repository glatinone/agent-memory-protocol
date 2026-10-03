"""ChromaDB implementation of StorageAdapter."""

from __future__ import annotations

import fnmatch
import json
from datetime import UTC, datetime
from typing import Any, cast

import chromadb

from amp_server.models import (
    LifecycleStatus,
    MemoryCell,
    MemoryCellUpdate,
    MemoryType,
    SearchRequest,
)
from amp_server.storage.base import (
    InvalidTransitionError,
    MemoryNotFoundError,
    StorageAdapter,
)

_IMMUTABLE_KEYS = frozenset({"id", "type", "amp_version", "identity"})

# The whole cell is stored as one JSON blob under this metadata key. Chroma
# metadata values must be scalars, so the cell cannot be stored field-by-field.
_CELL_JSON_KEY = "_cell_json"

# Search ranking blend: how much weight vector similarity vs. the cell's
# current decay score (spec §7 — importance x confidence x e^-decay*Δt)
# carries in the final ordering. Without this, `compute_decay_score` only
# ever drove active->stale->archived transitions and had no effect on
# ranking, so two cells with identical text but very different freshness/
# importance came back in an arbitrary vector-distance order.
_SIMILARITY_WEIGHT = 0.7
_DECAY_WEIGHT = 0.3


def _combined_score(similarity: float, cell: MemoryCell) -> float:
    """Blend vector similarity with decay so relevance still dominates
    (a barely-related but fresh cell should not outrank a highly relevant
    one), while a stale/low-importance duplicate ranks below a fresher,
    more important one at similar relevance."""
    # Deferred import: amp_server.lifecycle imports amp_server.storage.base,
    # and importing amp_server.storage.base triggers amp_server/storage/__init__.py,
    # which imports this module — a module-level import here would be circular.
    from amp_server.lifecycle import compute_decay_score

    decay = compute_decay_score(cell)
    return _SIMILARITY_WEIGHT * max(0.0, similarity) + _DECAY_WEIGHT * decay


def _serialize_cell(cell: MemoryCell) -> dict[str, Any]:
    """Convert a MemoryCell to a JSON-safe dict (all datetimes as ISO strings)."""
    return json.loads(cell.model_dump_json())


def _deserialize_cell(data: dict[str, Any]) -> MemoryCell:
    """Reconstruct a MemoryCell from a stored dict."""
    return MemoryCell.model_validate(data)


def _as_list(value: Any) -> list[Any]:
    """Narrow a Chroma result field to a list.

    Chroma's stubs type every result field as a union that includes None and
    scalar values, so indexing one directly is a type error. The actual shape
    is known at each call site; the narrowing lives here instead of in a cast
    at every use.
    """
    return cast("list[Any]", value) if value else []


def _cell_from_metadata(meta: Any) -> MemoryCell:
    """Decode a cell from the single JSON blob stored as its Chroma metadata."""
    return _deserialize_cell(json.loads(str(meta[_CELL_JSON_KEY])))


def _agent_can_read(cell: MemoryCell, agent_id: str) -> bool:
    """Check if agent_id has read access to cell, per spec §8."""
    if cell.access_policy.public:
        return True
    if agent_id == cell.identity.owner_id:
        return True
    if cell.identity.created_by and agent_id == cell.identity.created_by:
        return True
    return any(
        fnmatch.fnmatch(agent_id, pattern)
        for pattern in cell.access_policy.readable_by
        if pattern != "owner"
    )


class ChromaAdapter(StorageAdapter):
    def __init__(
        self,
        persist_directory: str | None = None,
        collection_name: str = "amp_memories",
    ) -> None:
        if persist_directory:
            self._client = chromadb.PersistentClient(path=persist_directory)
        else:
            self._client = chromadb.EphemeralClient()
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    async def save(self, cell: MemoryCell) -> str:
        cell_data = _serialize_cell(cell)
        self._collection.add(
            ids=[cell.id],
            documents=[cell.content.text],
            metadatas=[{_CELL_JSON_KEY: json.dumps(cell_data)}],
        )
        return cell.id

    async def get(self, memory_id: str) -> MemoryCell:
        """Return a cell and apply the access boost (access_count, last_accessed_at)."""
        results = self._collection.get(ids=[memory_id], include=["metadatas"])
        metadatas = _as_list(results["metadatas"])
        if not results["ids"] or not metadatas:
            raise MemoryNotFoundError(memory_id)
        cell = _cell_from_metadata(metadatas[0])
        cell.scoring.access_count += 1
        cell.lifecycle.last_accessed_at = datetime.now(UTC)
        await self._update_internal(memory_id, cell)
        return cell

    async def update(
        self, memory_id: str, updates: MemoryCellUpdate | dict[str, Any]
    ) -> MemoryCell:
        cell = await self._get_raw(memory_id)
        cell_dict = _serialize_cell(cell)
        if isinstance(updates, dict):
            updates_dict = updates
        else:
            # model_dump_json serializes datetimes to ISO strings, so the
            # result is safe to hand to json.dumps.
            updates_dict = json.loads(updates.model_dump_json(exclude_none=True))
        self._apply_updates(cell_dict, updates_dict)
        cell_dict["lifecycle"]["last_updated_at"] = datetime.now(UTC).isoformat()
        updated_cell = _deserialize_cell(cell_dict)
        await self._update_internal(memory_id, updated_cell)
        return updated_cell

    async def mark_deleted(self, memory_id: str) -> None:
        """Transition to 'deleted'. Retains the record per spec §6.3 (GDPR window)."""
        cell = await self._get_raw(memory_id)
        if cell.lifecycle.status != LifecycleStatus.ARCHIVED:
            raise InvalidTransitionError(
                f"Cannot delete cell with status '{cell.lifecycle.status}'. "
                "Archive it first."
            )
        cell_dict = _serialize_cell(cell)
        cell_dict["lifecycle"]["status"] = LifecycleStatus.DELETED.value
        cell_dict["lifecycle"]["last_updated_at"] = datetime.now(UTC).isoformat()
        updated_cell = _deserialize_cell(cell_dict)
        await self._update_internal(memory_id, updated_cell)

    async def purge(self, memory_id: str) -> None:
        """Physically remove cell. Only valid when status is 'deleted'."""
        cell = await self._get_raw(memory_id)
        if cell.lifecycle.status != LifecycleStatus.DELETED:
            raise InvalidTransitionError(
                f"Cannot purge cell with status '{cell.lifecycle.status}'. "
                "Only deleted cells can be purged."
            )
        self._collection.delete(ids=[memory_id])

    async def search(self, request: SearchRequest, agent_id: str) -> list[MemoryCell]:
        count = self._collection.count()
        if count == 0:
            return []

        # Rank over the full collection, not just the top `limit` by raw
        # vector distance: decay-weighted re-ranking can only surface a
        # fresher/more important cell above a stale one if it was actually
        # fetched. This mirrors `query()`'s existing scale posture (also
        # unconditionally reads the whole collection) for this reference
        # implementation.
        results = self._collection.query(
            query_texts=[request.query],
            n_results=count,
            include=["metadatas", "distances"],
        )

        metadatas = _as_list(results["metadatas"])
        if not metadatas or not metadatas[0]:
            return []

        # Both lists come from the same query and are therefore parallel;
        # strict=False keeps zip's original truncating behaviour.
        distances = _as_list(results["distances"])

        status_filter = list(request.status)
        if request.include_stale and LifecycleStatus.STALE not in status_filter:
            status_filter.append(LifecycleStatus.STALE)

        scored: list[tuple[float, MemoryCell]] = []
        for meta, distance in zip(metadatas[0], distances[0], strict=False):
            cell = _cell_from_metadata(meta)

            if request.owner_id and cell.identity.owner_id != request.owner_id:
                continue

            if request.types and cell.type not in request.types:
                continue

            if cell.lifecycle.status not in status_filter:
                continue

            if not _agent_can_read(cell, agent_id):
                continue

            # Chroma's cosine distance is 1 - cosine_similarity.
            similarity = 1.0 - distance
            scored.append((_combined_score(similarity, cell), cell))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [cell for _, cell in scored[: request.limit]]

    async def query(
        self,
        owner_id: str | None,
        types: list[MemoryType] | None,
        status: list[LifecycleStatus] | None,
        limit: int,
    ) -> list[MemoryCell]:
        """Filter cells by structured criteria without semantic search."""
        all_cells = await self.list_all()
        result: list[MemoryCell] = []
        for cell in all_cells:
            if owner_id and cell.identity.owner_id != owner_id:
                continue
            if types and cell.type not in types:
                continue
            if status and cell.lifecycle.status not in status:
                continue
            result.append(cell)
            if len(result) >= limit:
                break
        return result

    async def list_by_owner(self, owner_id: str) -> list[MemoryCell]:
        all_cells = await self.list_all()
        return [c for c in all_cells if c.identity.owner_id == owner_id]

    async def list_all(self) -> list[MemoryCell]:
        count = self._collection.count()
        if count == 0:
            return []
        results = self._collection.get(include=["metadatas"])
        return [_cell_from_metadata(meta) for meta in _as_list(results["metadatas"])]

    async def _get_raw(self, memory_id: str) -> MemoryCell:
        """Get a MemoryCell without triggering the access boost."""
        results = self._collection.get(ids=[memory_id], include=["metadatas"])
        metadatas = _as_list(results["metadatas"])
        if not results["ids"] or not metadatas:
            raise MemoryNotFoundError(memory_id)
        return _cell_from_metadata(metadatas[0])

    async def _update_internal(self, memory_id: str, cell: MemoryCell) -> None:
        """Overwrite a cell's stored data in ChromaDB."""
        cell_data = _serialize_cell(cell)
        self._collection.update(
            ids=[memory_id],
            documents=[cell.content.text],
            metadatas=[{_CELL_JSON_KEY: json.dumps(cell_data)}],
        )

    @staticmethod
    def _apply_updates(target: dict, updates: dict, _root: bool = True) -> None:
        """Recursively merge updates into target, blocking immutable top-level keys."""
        for key, value in updates.items():
            if _root and key in _IMMUTABLE_KEYS:
                continue
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                ChromaAdapter._apply_updates(target[key], value, _root=False)
            else:
                target[key] = value
