"""ChromaDB implementation of StorageAdapter."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, cast

import chromadb

from amp_server.access_control import check_read_access
from amp_server.embeddings import (
    ChromaDefaultEmbeddingProvider,
    EmbeddingProvider,
    describe,
)
from amp_server.limits import enforce_cell_size
from amp_server.models import (
    LifecycleStatus,
    MemoryCell,
    MemoryCellUpdate,
    MemoryType,
    SearchRequest,
)
from amp_server.ranking import combined_score
from amp_server.retention import RETENTION_DAYS, enforce_retention_window
from amp_server.storage.base import (
    InvalidTransitionError,
    MemoryNotFoundError,
    StorageAdapter,
)
from amp_server.storage.records import apply_updates, deserialize_cell, serialize_cell

# The whole cell is stored as one JSON blob under this metadata key. Chroma
# metadata values must be scalars, so the cell cannot be stored field-by-field.
_CELL_JSON_KEY = "_cell_json"

# Search ranking is shared with every other backend; see amp_server.ranking.


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
    return deserialize_cell(json.loads(str(meta[_CELL_JSON_KEY])))


class ChromaAdapter(StorageAdapter):
    def __init__(
        self,
        persist_directory: str | None = None,
        collection_name: str = "amp_memories",
        embedding_provider: EmbeddingProvider | None = None,
        retention_days: int = RETENTION_DAYS,
    ) -> None:
        # A parameter rather than an env var: the spec fixes the window at 30
        # days, so an operator knob could only ever take it below the floor.
        # Tests use it to reach the post-window path without waiting 30 days.
        self._retention_days = retention_days
        if persist_directory:
            self._client = chromadb.PersistentClient(path=persist_directory)
        else:
            self._client = chromadb.EphemeralClient()
        self._embedding_provider = (
            embedding_provider or ChromaDefaultEmbeddingProvider()
        )
        # No embedding function on the collection: the adapter embeds through
        # the provider and hands Chroma finished vectors, so there is exactly
        # one place text becomes numbers and the provider can be swapped without
        # Chroma storing a model identity of its own.
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
            embedding_function=None,
        )

    @property
    def embedding(self) -> dict[str, Any]:
        """What embeds text here, for `GET /spec`."""
        return describe(self._embedding_provider)

    @property
    def retention_days(self) -> int:
        return self._retention_days

    def _embed(self, texts: list[str]) -> list[Any]:
        """Embed through the configured provider.

        Typed loosely on purpose: Chroma annotates `embeddings` as a union of
        sequence types, and a plain `list[list[float]]` does not satisfy it by
        invariance even though every element is a float and Chroma accepts it.
        The vectors themselves are typed where they are produced, in the
        provider.
        """
        return [list(vector) for vector in self._embedding_provider.embed(texts)]

    async def save(self, cell: MemoryCell) -> str:
        # Checked before anything is written, so a refused cell leaves no trace.
        enforce_cell_size(cell)
        cell_data = serialize_cell(cell)
        self._collection.add(
            ids=[cell.id],
            documents=[cell.content.text],
            embeddings=self._embed([cell.content.text]),
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
        cell_dict = serialize_cell(cell)
        if isinstance(updates, dict):
            updates_dict = updates
        else:
            # model_dump_json serializes datetimes to ISO strings, so the
            # result is safe to hand to json.dumps.
            updates_dict = json.loads(updates.model_dump_json(exclude_none=True))

        lifecycle_update = updates_dict.get("lifecycle") or {}
        if "status" in lifecycle_update:
            # Deferred import: amp_server.lifecycle imports this package's base
            # module, which triggers storage/__init__ and its import of this
            # module, so a module-level import here would be circular.
            from amp_server.lifecycle import check_status_transition

            try:
                target = LifecycleStatus(lifecycle_update["status"])
            except ValueError as exc:
                raise InvalidTransitionError(
                    f"unknown lifecycle status {lifecycle_update['status']!r}"
                ) from exc
            check_status_transition(cell.lifecycle.status, target)

        self._apply_updates(cell_dict, updates_dict)
        cell_dict["lifecycle"]["last_updated_at"] = datetime.now(UTC).isoformat()
        updated_cell = deserialize_cell(cell_dict)
        # Enforced on the merged result and before the write, so a PATCH cannot
        # grow a cell past the advertised maximum either.
        enforce_cell_size(updated_cell)
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
        cell_dict = serialize_cell(cell)
        cell_dict["lifecycle"]["status"] = LifecycleStatus.DELETED.value
        cell_dict["lifecycle"]["last_updated_at"] = datetime.now(UTC).isoformat()
        updated_cell = deserialize_cell(cell_dict)
        await self._update_internal(memory_id, updated_cell)

    async def purge(self, memory_id: str) -> None:
        """Physically remove a deleted cell, once its retention window has run."""
        cell = await self._get_raw(memory_id)
        if cell.lifecycle.status != LifecycleStatus.DELETED:
            raise InvalidTransitionError(
                f"Cannot purge cell with status '{cell.lifecycle.status}'. "
                "Only deleted cells can be purged."
            )
        enforce_retention_window(cell, self._retention_days)
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
            query_embeddings=self._embed([request.query]),
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

            if not check_read_access(cell, agent_id):
                continue

            # Chroma's cosine distance is 1 - cosine_similarity.
            similarity = 1.0 - distance
            scored.append((combined_score(similarity, cell), cell))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [cell for _, cell in scored[: request.limit]]

    async def query(
        self,
        owner_id: str | None,
        types: list[MemoryType] | None,
        status: list[LifecycleStatus] | None,
        limit: int,
        offset: int = 0,
    ) -> list[MemoryCell]:
        """Filter cells by structured criteria without semantic search.

        One pass over the collection: the metadata filter is applied in Python
        because the whole cell is stored as a single JSON blob (Chroma metadata
        holds scalars only), so there is no field for the store to filter on.
        """
        all_cells = await self.list_all()
        result: list[MemoryCell] = []
        matched = 0
        for cell in all_cells:
            if owner_id and cell.identity.owner_id != owner_id:
                continue
            if types and cell.type not in types:
                continue
            if status and cell.lifecycle.status not in status:
                continue
            matched += 1
            if matched <= offset:
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
        cell_data = serialize_cell(cell)
        self._collection.update(
            ids=[memory_id],
            documents=[cell.content.text],
            embeddings=self._embed([cell.content.text]),
            metadatas=[{_CELL_JSON_KEY: json.dumps(cell_data)}],
        )

    @staticmethod
    def _apply_updates(target: dict, updates: dict, _root: bool = True) -> None:
        """Kept as a thin delegate so the call site reads the same as before.

        The merge rule itself is shared with every other backend
        (`amp_server.storage.records.apply_updates`).
        """
        apply_updates(target, updates)
