"""PostgreSQL + pgvector implementation of StorageAdapter.

Chroma is an embedded store: fine for a reference deployment and a single
process, and not what a team already running infrastructure has. This adapter
keeps memory cells in a Postgres table with a `vector` column, so AMP can sit
next to the data it is already next to, be backed up by the tooling already in
place, and survive more than one server process.

Ranking is not reimplemented here: `amp_server.ranking.combined_score` decides
the order for every backend, so the same data returns the same order whatever it
is stored in. The same is true of the record rules in
`amp_server.storage.records`.

`psycopg` is an optional dependency (`pip install amp-server[postgres]`),
imported inside the constructor so the module can be imported without it. The
`pgvector` *Python* package is not used: vectors are sent in pgvector's text
format with an explicit `::vector` cast, which is one less adapter to depend on
and behaves the same across driver versions.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

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

# The cell is stored once as JSONB and indexed into columns for the fields a
# query filters on. Storing it in both places would let them disagree.
TABLE = "amp_memories"


def _require_driver() -> Any:
    """Import the optional driver, with an error that says how to fix it."""
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - exercised by the message only
        raise ImportError(
            "the postgres backend needs its optional dependency: "
            'pip install "amp-server[postgres]"'
        ) from exc
    return psycopg


def _vector_literal(vector: Sequence[float]) -> str:
    """Render a vector in pgvector's text format, `[1,2,3]`.

    Passing the text form with an explicit `::vector` cast avoids depending on
    pgvector's own Python adapters, which differ between driver versions.
    """
    return "[" + ",".join(repr(float(value)) for value in vector) + "]"


class PostgresAdapter(StorageAdapter):
    """Stores memory cells in Postgres, with pgvector for similarity search."""

    def __init__(
        self,
        *,
        dsn: str,
        embedding_provider: EmbeddingProvider | None = None,
        table: str = TABLE,
        retention_days: int = RETENTION_DAYS,
    ) -> None:
        # See the Chroma adapter: a parameter, not an env var, because the spec
        # fixes the floor at 30 days.
        self._retention_days = retention_days
        psycopg = _require_driver()
        self._psycopg = psycopg
        self._table = table
        self._embedding_provider = (
            embedding_provider or ChromaDefaultEmbeddingProvider()
        )
        self._connection = psycopg.connect(dsn, autocommit=True)
        self._prepare_schema()

    # -- schema ------------------------------------------------------------

    @property
    def _dimensions(self) -> int | None:
        return self._embedding_provider.dimensions

    def _prepare_schema(self) -> None:
        """Create the extension, table and indexes if they are not there yet.

        `CREATE EXTENSION` needs a superuser or the extension pre-installed. If it
        fails, the error is left to surface: a table without its vector column
        would fail later and less clearly.
        """
        dimensions = self._dimensions
        # pgvector needs a fixed width to build an index, so an unconstrained
        # column is used when the provider does not declare one.
        column = f"vector({dimensions})" if dimensions else "vector"

        with self._connection.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._table} (
                    id        TEXT PRIMARY KEY,
                    owner_id  TEXT NOT NULL,
                    type      TEXT NOT NULL,
                    status    TEXT NOT NULL,
                    content   TEXT NOT NULL,
                    cell      JSONB NOT NULL,
                    embedding {column} NOT NULL
                )
                """
            )
            # The two filters every query path uses.
            cursor.execute(
                f"CREATE INDEX IF NOT EXISTS {self._table}_owner_idx "
                f"ON {self._table} (owner_id)"
            )
            cursor.execute(
                f"CREATE INDEX IF NOT EXISTS {self._table}_status_idx "
                f"ON {self._table} (status)"
            )
            if dimensions:
                # Cosine distance, matching the collection metric the Chroma
                # adapter configures, so both rank on the same measure.
                cursor.execute(
                    f"CREATE INDEX IF NOT EXISTS {self._table}_embedding_idx "
                    f"ON {self._table} USING hnsw (embedding vector_cosine_ops)"
                )

    # -- StorageAdapter ----------------------------------------------------

    @property
    def embedding(self) -> dict[str, Any]:
        """What embeds text here, for `GET /spec`."""
        return describe(self._embedding_provider)

    @property
    def retention_days(self) -> int:
        return self._retention_days

    async def save(self, cell: MemoryCell) -> str:
        # Checked before anything is written, so a refused cell leaves no trace.
        enforce_cell_size(cell)
        cell_data = serialize_cell(cell)
        with self._connection.cursor() as cursor:
            cursor.execute(
                f"""
                INSERT INTO {self._table}
                    (id, owner_id, type, status, content, cell, embedding)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::vector)
                """,
                (
                    cell.id,
                    cell.identity.owner_id,
                    cell.type.value,
                    cell.lifecycle.status.value,
                    cell.content.text,
                    json.dumps(cell_data),
                    _vector_literal(self._embed([cell.content.text])[0]),
                ),
            )
        return cell.id

    async def get(self, memory_id: str) -> MemoryCell:
        """Return a cell and apply the access boost (access_count, last_accessed_at)."""
        cell = await self._get_raw(memory_id)
        cell.scoring.access_count += 1
        cell.lifecycle.last_accessed_at = datetime.now(UTC)
        await self._write_cell(cell)
        return cell

    async def update(
        self, memory_id: str, updates: MemoryCellUpdate | dict[str, Any]
    ) -> MemoryCell:
        cell = await self._get_raw(memory_id)
        cell_dict = serialize_cell(cell)
        if isinstance(updates, dict):
            updates_dict = updates
        else:
            updates_dict = json.loads(updates.model_dump_json(exclude_none=True))

        lifecycle_update = updates_dict.get("lifecycle") or {}
        if "status" in lifecycle_update:
            # Deferred import: amp_server.lifecycle imports this package's base
            # module, so a module-level import here would be circular.
            from amp_server.lifecycle import check_status_transition

            try:
                target = LifecycleStatus(lifecycle_update["status"])
            except ValueError as exc:
                raise InvalidTransitionError(
                    f"unknown lifecycle status {lifecycle_update['status']!r}"
                ) from exc
            check_status_transition(cell.lifecycle.status, target)

        apply_updates(cell_dict, updates_dict)
        cell_dict["lifecycle"]["last_updated_at"] = datetime.now(UTC).isoformat()
        updated_cell = deserialize_cell(cell_dict)
        # Enforced on the merged result and before the write, so a PATCH cannot
        # grow a cell past the advertised maximum either.
        enforce_cell_size(updated_cell)
        await self._write_cell(updated_cell)
        return updated_cell

    async def mark_deleted(self, memory_id: str) -> None:
        """Transition to 'deleted'. Retains the record per spec §6.3 (GDPR window)."""
        cell = await self._get_raw(memory_id)
        if cell.lifecycle.status != LifecycleStatus.ARCHIVED:
            raise InvalidTransitionError(
                f"Cannot delete cell with status '{cell.lifecycle.status}'. "
                "Archive it first."
            )
        cell.lifecycle.status = LifecycleStatus.DELETED
        cell.lifecycle.last_updated_at = datetime.now(UTC)
        await self._write_cell(cell)

    async def purge(self, memory_id: str) -> None:
        """Physically remove a deleted cell, once its retention window has run."""
        cell = await self._get_raw(memory_id)
        if cell.lifecycle.status != LifecycleStatus.DELETED:
            raise InvalidTransitionError(
                f"Cannot purge cell with status '{cell.lifecycle.status}'. "
                "Only deleted cells can be purged."
            )
        enforce_retention_window(cell, self._retention_days)
        with self._connection.cursor() as cursor:
            cursor.execute(f"DELETE FROM {self._table} WHERE id = %s", (memory_id,))

    async def search(self, request: SearchRequest, agent_id: str) -> list[MemoryCell]:
        status_filter = list(request.status)
        if request.include_stale and LifecycleStatus.STALE not in status_filter:
            status_filter.append(LifecycleStatus.STALE)

        conditions = ["status = ANY(%s::text[])"]
        params: list[Any] = [
            _vector_literal(self._embed([request.query])[0]),
            [s.value for s in status_filter],
        ]
        if request.owner_id:
            conditions.append("owner_id = %s")
            params.append(request.owner_id)
        if request.types:
            conditions.append("type = ANY(%s::text[])")
            params.append([t.value for t in request.types])

        where = " AND ".join(conditions)
        with self._connection.cursor() as cursor:
            # `<=>` is cosine distance, so similarity is 1 - distance: the same
            # conversion the Chroma adapter applies to its distances.
            cursor.execute(
                f"""
                SELECT cell, embedding <=> %s::vector AS distance
                FROM {self._table}
                WHERE {where}
                """,
                params,
            )
            rows = cursor.fetchall()

        scored: list[tuple[float, MemoryCell]] = []
        for cell_data, distance in rows:
            cell = deserialize_cell(cell_data)
            if not check_read_access(cell, agent_id):
                continue
            similarity = 1.0 - float(distance)
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
        """Filter cells by structured criteria without semantic search."""
        conditions: list[str] = []
        params: list[Any] = []
        if owner_id:
            conditions.append("owner_id = %s")
            params.append(owner_id)
        if types:
            conditions.append("type = ANY(%s::text[])")
            params.append([t.value for t in types])
        if status:
            conditions.append("status = ANY(%s::text[])")
            params.append([s.value for s in status])
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend((limit, offset))

        with self._connection.cursor() as cursor:
            cursor.execute(
                f"SELECT cell FROM {self._table} {where} LIMIT %s OFFSET %s", params
            )
            rows = cursor.fetchall()
        return [deserialize_cell(row[0]) for row in rows]

    async def list_by_owner(self, owner_id: str) -> list[MemoryCell]:
        with self._connection.cursor() as cursor:
            cursor.execute(
                f"SELECT cell FROM {self._table} WHERE owner_id = %s", (owner_id,)
            )
            rows = cursor.fetchall()
        return [deserialize_cell(row[0]) for row in rows]

    async def list_all(self) -> list[MemoryCell]:
        with self._connection.cursor() as cursor:
            cursor.execute(f"SELECT cell FROM {self._table}")
            rows = cursor.fetchall()
        return [deserialize_cell(row[0]) for row in rows]

    def close(self) -> None:
        """Release the connection. Not part of StorageAdapter; used by the lifespan."""
        self._connection.close()

    # -- internals ---------------------------------------------------------

    def _embed(self, texts: list[str]) -> list[Any]:
        return [list(vector) for vector in self._embedding_provider.embed(texts)]

    async def _get_raw(self, memory_id: str) -> MemoryCell:
        """Get a cell without triggering the access boost."""
        with self._connection.cursor() as cursor:
            cursor.execute(
                f"SELECT cell FROM {self._table} WHERE id = %s", (memory_id,)
            )
            row = cursor.fetchone()
        if row is None:
            raise MemoryNotFoundError(memory_id)
        return deserialize_cell(row[0])

    async def _write_cell(self, cell: MemoryCell) -> None:
        """Overwrite a stored cell, including its indexed columns and vector."""
        cell_data = serialize_cell(cell)
        with self._connection.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE {self._table}
                   SET owner_id = %s, type = %s, status = %s, content = %s,
                       cell = %s::jsonb, embedding = %s::vector
                 WHERE id = %s
                """,
                (
                    cell.identity.owner_id,
                    cell.type.value,
                    cell.lifecycle.status.value,
                    cell.content.text,
                    json.dumps(cell_data),
                    _vector_literal(self._embed([cell.content.text])[0]),
                    cell.id,
                ),
            )
