"""The behaviour every storage backend has to share.

A second backend is only useful if it behaves like the first one. These tests run
against both and assert the parts the protocol depends on: the record lifecycle,
the transition rules, the size limit, the filters, and - the one that matters
most - that two backends rank the same data the same way.

The ranking test is the reason `amp_server.ranking` and
`amp_server.storage.records` exist. Before them, each adapter carried its own copy
of the blend and the patch-merge, and the read-access rule in this repository
already drifted once when it was duplicated that way.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import pytest
from conftest import make_cell, postgres_or_skip

from amp_server.embeddings import EmbeddingProvider
from amp_server.models import (
    LifecycleStatus,
    MemoryCellUpdate,
    SearchRequest,
)
from amp_server.retention import RETENTION_DAYS, RetentionWindowError
from amp_server.storage.base import InvalidTransitionError, MemoryNotFoundError
from amp_server.storage.chroma import ChromaAdapter

_OWNER = "user-backends"
_CREATOR = "agent-backends"


class KeywordEmbedding(EmbeddingProvider):
    """Deterministic vectors: one dimension per keyword, so ranking is testable."""

    name = "stub-keywords"
    dimensions = 3
    KEYWORDS = ("email", "invoice", "python")

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [
            [float(keyword in text.lower()) for keyword in self.KEYWORDS]
            for text in texts
        ]


def _search(query: str, owner_id: str = _OWNER) -> SearchRequest:
    return SearchRequest(query=query, owner_id=owner_id, limit=10)


def _open_adapter(backend: str, **kwargs):
    """Build a backend, and return it with whatever teardown it needs.

    One factory for every fixture below: a fixture that builds its own adapter
    would be a second place to update when a constructor argument changes.
    """
    provider = KeywordEmbedding()
    if backend == "chroma":
        return (
            ChromaAdapter(
                collection_name=f"test_{uuid.uuid4().hex[:12]}",
                embedding_provider=provider,
                **kwargs,
            ),
            None,
        )

    from amp_server.storage.postgres import PostgresAdapter

    table = f"amp_test_{uuid.uuid4().hex[:12]}"
    adapter = PostgresAdapter(
        dsn=postgres_or_skip(),
        table=table,
        embedding_provider=provider,
        **kwargs,
    )
    return adapter, table


def _close_adapter(adapter, table: str | None) -> None:
    if table is None:
        return
    with adapter._connection.cursor() as cursor:
        cursor.execute(f"DROP TABLE IF EXISTS {table}")
    adapter.close()


@pytest.fixture(params=["chroma", "postgres"])
def adapter(request):
    """The same interface, built on each backend."""
    built, table = _open_adapter(request.param)
    yield built
    _close_adapter(built, table)


@pytest.fixture(params=["chroma", "postgres"])
def expired_adapter(request):
    """A backend whose retention window is already over.

    The window is a constructor argument rather than an environment variable,
    because the spec fixes the floor at 30 days; this is how the path past the
    window is reached without a test waiting a month.
    """
    built, table = _open_adapter(request.param, retention_days=0)
    yield built
    _close_adapter(built, table)


# ---------------------------------------------------------------------------
# The record lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_then_get_returns_the_same_cell(adapter):
    cell = make_cell(owner_id=_OWNER, created_by=_CREATOR, text="please email me")
    assert await adapter.save(cell) == cell.id

    found = await adapter.get(cell.id)

    assert found.id == cell.id
    assert found.content.text == "please email me"
    assert found.identity.owner_id == _OWNER


@pytest.mark.asyncio
async def test_get_increments_the_access_count(adapter):
    cell = make_cell(owner_id=_OWNER, created_by=_CREATOR)
    await adapter.save(cell)

    first = await adapter.get(cell.id)
    second = await adapter.get(cell.id)

    assert first.scoring.access_count == 1
    assert second.scoring.access_count == 2


@pytest.mark.asyncio
async def test_get_of_an_unknown_id_raises(adapter):
    with pytest.raises(MemoryNotFoundError):
        await adapter.get("mem_01J5A3B7K9M2N4P6Q8R0S1T3V5")


@pytest.mark.asyncio
async def test_a_patch_merges_without_touching_immutable_fields(adapter):
    cell = make_cell(owner_id=_OWNER, created_by=_CREATOR, text="first text")
    await adapter.save(cell)

    updated = await adapter.update(
        cell.id, {"content": {"text": "second text"}, "id": "mem_SHOULD_NOT_CHANGE"}
    )

    assert updated.content.text == "second text"
    assert updated.id == cell.id
    assert updated.type == cell.type
    assert updated.identity.owner_id == _OWNER


@pytest.mark.asyncio
async def test_the_archive_then_delete_flow_works(adapter):
    cell = make_cell(owner_id=_OWNER, created_by=_CREATOR)
    await adapter.save(cell)

    archived = await adapter.update(
        cell.id,
        {"lifecycle": {"created_at": cell.lifecycle.created_at, "status": "archived"}},
    )
    assert archived.lifecycle.status is LifecycleStatus.ARCHIVED

    await adapter.mark_deleted(cell.id)

    assert (await adapter._get_raw(cell.id)).lifecycle.status is LifecycleStatus.DELETED


@pytest.mark.asyncio
async def test_deleting_an_active_cell_is_refused(adapter):
    cell = make_cell(
        owner_id=_OWNER, created_by=_CREATOR, status=LifecycleStatus.ACTIVE
    )
    await adapter.save(cell)

    with pytest.raises(InvalidTransitionError):
        await adapter.mark_deleted(cell.id)


@pytest.mark.asyncio
async def test_a_write_cannot_reach_deleted(adapter):
    """Spec §2: use DELETE, and DELETE needs the cell archived first."""
    cell = make_cell(
        owner_id=_OWNER, created_by=_CREATOR, status=LifecycleStatus.ACTIVE
    )
    await adapter.save(cell)

    with pytest.raises(InvalidTransitionError):
        await adapter.update(
            cell.id,
            {
                "lifecycle": {
                    "created_at": cell.lifecycle.created_at,
                    "status": "deleted",
                }
            },
        )


@pytest.mark.asyncio
async def test_an_archived_cell_cannot_return_to_active(adapter):
    cell = make_cell(
        owner_id=_OWNER, created_by=_CREATOR, status=LifecycleStatus.ARCHIVED
    )
    await adapter.save(cell)

    with pytest.raises(InvalidTransitionError):
        await adapter.update(
            cell.id,
            {
                "lifecycle": {
                    "created_at": cell.lifecycle.created_at,
                    "status": "active",
                }
            },
        )


@pytest.mark.asyncio
async def test_purge_removes_a_deleted_cell_for_good(expired_adapter):
    """Erased for good — but only once the window is over.

    This case used to purge a cell one instant after deleting it, which is what
    the retention rule now refuses (see the window tests above). The destructive
    half still has to be proven, so it runs against an adapter whose window is
    already past.
    """
    cell = make_cell(
        owner_id=_OWNER, created_by=_CREATOR, status=LifecycleStatus.ARCHIVED
    )
    await expired_adapter.save(cell)
    await expired_adapter.mark_deleted(cell.id)

    await expired_adapter.purge(cell.id)

    with pytest.raises(MemoryNotFoundError):
        await expired_adapter._get_raw(cell.id)


@pytest.mark.asyncio
async def test_purging_a_live_cell_is_refused(adapter):
    cell = make_cell(
        owner_id=_OWNER, created_by=_CREATOR, status=LifecycleStatus.ACTIVE
    )
    await adapter.save(cell)

    with pytest.raises(InvalidTransitionError):
        await adapter.purge(cell.id)


@pytest.mark.asyncio
async def test_the_size_limit_is_enforced_before_writing(adapter):
    from amp_server.errors import AMPError

    cell = make_cell(owner_id=_OWNER, created_by=_CREATOR, text="x" * 70_000)

    with pytest.raises(AMPError) as raised:
        await adapter.save(cell)

    assert raised.value.code == "CELL_TOO_LARGE"
    with pytest.raises(MemoryNotFoundError):
        await adapter._get_raw(cell.id)


@pytest.mark.asyncio
async def test_purge_is_refused_inside_the_retention_window(adapter):
    """Spec lifecycle.md §5: purge is preconditioned on the window elapsing.

    Both backends must refuse, and refuse it themselves: the rule living in a
    docstring that asked the caller to wait is what this replaced.
    """
    cell = make_cell(
        owner_id=_OWNER, created_by=_CREATOR, status=LifecycleStatus.ARCHIVED
    )
    await adapter.save(cell)
    await adapter.mark_deleted(cell.id)

    with pytest.raises(RetentionWindowError, match="retained until"):
        await adapter.purge(cell.id)

    # Refused means nothing was removed.
    assert (await adapter._get_raw(cell.id)).lifecycle.status is LifecycleStatus.DELETED


@pytest.mark.asyncio
async def test_purge_succeeds_once_the_window_has_elapsed(expired_adapter):
    cell = make_cell(
        owner_id=_OWNER, created_by=_CREATOR, status=LifecycleStatus.ARCHIVED
    )
    await expired_adapter.save(cell)
    await expired_adapter.mark_deleted(cell.id)

    await expired_adapter.purge(cell.id)

    with pytest.raises(MemoryNotFoundError):
        await expired_adapter._get_raw(cell.id)


@pytest.mark.asyncio
async def test_a_live_cell_is_refused_before_the_window_is_even_considered(adapter):
    """Status is checked first, so the error names the real problem."""
    cell = make_cell(
        owner_id=_OWNER, created_by=_CREATOR, status=LifecycleStatus.ACTIVE
    )
    await adapter.save(cell)

    with pytest.raises(InvalidTransitionError, match="Only deleted cells"):
        await adapter.purge(cell.id)


# ---------------------------------------------------------------------------
# Listing and filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_filters_by_owner_type_and_status(adapter):
    await adapter.save(
        make_cell(owner_id=_OWNER, created_by=_CREATOR, text="semantic one")
    )
    await adapter.save(
        make_cell(owner_id="user-other", created_by=_CREATOR, text="someone else")
    )

    results = await adapter.query(
        owner_id=_OWNER, types=None, status=[LifecycleStatus.ACTIVE], limit=10
    )

    assert [cell.identity.owner_id for cell in results] == [_OWNER]


@pytest.mark.asyncio
async def test_query_windows_the_filtered_result(adapter):
    """`offset` pages through matches, identically on every backend.

    Identical matters: a client that pages one backend and then another must see
    the same cells in the same order, so the window is over the *filtered* set.
    """
    stored = []
    for index in range(5):
        cell = make_cell(owner_id=_OWNER, created_by=_CREATOR, text=f"windowed {index}")
        await adapter.save(cell)
        stored.append(cell.id)
    # A cell that does not match, so the window cannot be over all rows.
    await adapter.save(
        make_cell(owner_id="user-other", created_by=_CREATOR, text="other")
    )

    first = await adapter.query(
        owner_id=_OWNER, types=None, status=None, limit=2, offset=0
    )
    second = await adapter.query(
        owner_id=_OWNER, types=None, status=None, limit=2, offset=2
    )
    beyond = await adapter.query(
        owner_id=_OWNER, types=None, status=None, limit=2, offset=99
    )

    assert [len(first), len(second)] == [2, 2]
    assert {c.id for c in first} | {c.id for c in second} <= set(stored)
    assert not ({c.id for c in first} & {c.id for c in second})
    assert beyond == []


@pytest.mark.asyncio
async def test_list_by_owner_and_list_all_agree(adapter):
    await adapter.save(make_cell(owner_id=_OWNER, created_by=_CREATOR, text="mine"))
    await adapter.save(
        make_cell(owner_id="user-other", created_by=_CREATOR, text="theirs")
    )

    mine = await adapter.list_by_owner(_OWNER)
    everything = await adapter.list_all()

    assert len(mine) == 1
    assert len(everything) == 2
    assert {cell.id for cell in mine} <= {cell.id for cell in everything}


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_filters_to_cells_the_agent_may_read(adapter):
    await adapter.save(
        make_cell(
            owner_id=_OWNER,
            created_by=_CREATOR,
            text="please email me",
            readable_by=["agent_reader*"],
        )
    )

    allowed = await adapter.search(_search("email"), agent_id="agent_reader_1")
    refused = await adapter.search(_search("email"), agent_id="agent_stranger")

    assert len(allowed) == 1
    assert refused == []


@pytest.mark.asyncio
async def test_search_can_include_stale_cells(adapter):
    await adapter.save(
        make_cell(
            owner_id=_OWNER,
            created_by=_CREATOR,
            text="an invoice",
            status=LifecycleStatus.STALE,
        )
    )

    request = _search("invoice")
    without_stale = await adapter.search(request, agent_id=_OWNER)

    request.include_stale = True
    with_stale = await adapter.search(request, agent_id=_OWNER)

    assert without_stale == []
    assert len(with_stale) == 1


@pytest.mark.asyncio
async def test_search_windows_the_ranked_result(adapter):
    """`offset` pages the *readable* ranked matches, on every backend.

    Windows must mean the same thing here as in `query`: a client that pages one
    backend and then another has to see the same cells in the same order.
    """
    ids = []
    for index in range(4):
        cell = make_cell(owner_id=_OWNER, created_by=_CREATOR, text=f"invoice {index}")
        await adapter.save(cell)
        ids.append(cell.id)

    request = SearchRequest(query="invoice", owner_id=_OWNER, limit=2)
    first = await adapter.search(request, agent_id=_OWNER)

    request = SearchRequest(query="invoice", owner_id=_OWNER, limit=2, offset=2)
    second = await adapter.search(request, agent_id=_OWNER)

    request = SearchRequest(query="invoice", owner_id=_OWNER, limit=2, offset=99)
    beyond = await adapter.search(request, agent_id=_OWNER)

    assert [len(first), len(second)] == [2, 2]
    assert not ({c.id for c in first} & {c.id for c in second})
    assert {c.id for c in first} | {c.id for c in second} == set(ids)
    assert beyond == []


@pytest.mark.asyncio
async def test_search_windows_after_the_access_filter(adapter):
    """A page counts cells the caller may read, not cells ranked ahead of them."""
    await adapter.save(
        make_cell(
            owner_id=_OWNER,
            created_by=_CREATOR,
            text="invoice for someone else",
            readable_by=["agent_elsewhere*"],
        )
    )
    for index in range(2):
        await adapter.save(
            make_cell(
                owner_id=_OWNER,
                created_by=_CREATOR,
                text=f"invoice {index}",
                readable_by=["agent_reader*"],
            )
        )

    request = SearchRequest(query="invoice", owner_id=_OWNER, limit=2)
    results = await adapter.search(request, agent_id="agent_reader_1")

    assert len(results) == 2, "the unreadable cell was counted against the limit"


@pytest.mark.asyncio
async def test_search_honours_the_limit(adapter):
    for index in range(5):
        await adapter.save(
            make_cell(owner_id=_OWNER, created_by=_CREATOR, text=f"invoice {index}")
        )

    request = SearchRequest(query="invoice", owner_id=_OWNER, limit=2)
    results = await adapter.search(request, agent_id=_OWNER)

    assert len(results) == 2


# ---------------------------------------------------------------------------
# Cross-backend agreement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_both_backends_rank_the_same_data_the_same_way():
    """The invariant that justified sharing the ranking rule.

    Two adapters, the same deterministic embeddings, the same cells: the order
    has to match. If the blend lived in both adapters, this test is what would
    catch them drifting.
    """
    from datetime import UTC, datetime, timedelta

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
    )
    from amp_server.ranking import combined_score

    now = datetime.now(UTC)
    cells = []
    for text, importance, age_days in [
        ("invoice for last month", 0.9, 0.0),
        ("invoice, older and less important", 0.4, 40.0),
        ("unrelated note about python", 0.5, 1.0),
    ]:
        cells.append(
            MemoryCell(
                type=MemoryType.SEMANTIC,
                content=MemoryContent(text=text),
                identity=MemoryIdentity(
                    owner_id=_OWNER, owner_type=OwnerType.USER, created_by=_CREATOR
                ),
                lifecycle=MemoryLifecycle(
                    created_at=now - timedelta(days=age_days),
                    status=LifecycleStatus.ACTIVE,
                ),
                scoring=MemoryScoring(importance=importance),
                access_policy=MemoryAccessPolicy(),
            )
        )

    provider = KeywordEmbedding()
    chroma = ChromaAdapter(
        collection_name=f"test_{uuid.uuid4().hex[:12]}", embedding_provider=provider
    )
    from amp_server.storage.postgres import PostgresAdapter

    table = f"amp_test_{uuid.uuid4().hex[:12]}"
    postgres = PostgresAdapter(
        dsn=postgres_or_skip(), table=table, embedding_provider=provider
    )
    try:
        for cell in cells:
            await chroma.save(cell)
            await postgres.save(cell)

        request = SearchRequest(query="invoice", owner_id=_OWNER, limit=10)
        chroma_order = [c.id for c in await chroma.search(request, agent_id=_OWNER)]
        postgres_order = [c.id for c in await postgres.search(request, agent_id=_OWNER)]

        assert chroma_order == postgres_order
        assert len(chroma_order) == 3

        # And the order is the documented blend, not an accident of the store.
        expected = sorted(
            cells,
            key=lambda cell: combined_score(
                1.0 - _cosine_distance(provider, "invoice", cell.content.text), cell
            ),
            reverse=True,
        )
        assert chroma_order == [cell.id for cell in expected]
    finally:
        with postgres._connection.cursor() as cursor:
            cursor.execute(f"DROP TABLE IF EXISTS {table}")
        postgres.close()


def _cosine_distance(provider: EmbeddingProvider, left: str, right: str) -> float:
    """The same measure both adapters rank on."""
    a, b = provider.embed([left])[0], provider.embed([right])[0]
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 1.0
    return 1.0 - dot / (norm_a * norm_b)


# ---------------------------------------------------------------------------
# What can be checked without a database
# ---------------------------------------------------------------------------


def test_the_vector_literal_matches_pgvectors_text_format():
    """The Postgres adapter sends vectors as text with a `::vector` cast.

    pgvector's own Python adapters differ between driver versions, so the value
    is formatted here instead. This is the one part of that adapter a machine
    without Postgres can still verify, so it is pinned exactly.
    """
    from amp_server.storage.postgres import _vector_literal

    assert _vector_literal([0.0, 1.0, -0.5]) == "[0.0,1.0,-0.5]"
    assert _vector_literal([1]) == "[1.0]"
    assert _vector_literal([]) == "[]"
    # ints become floats, and exponent form round-trips through the same parser
    assert _vector_literal([1e-05]) == "[1e-05]"


def test_the_postgres_adapter_says_which_dependency_is_missing():
    """The optional driver is imported inside the constructor, on purpose."""
    import amp_server.storage.postgres as module

    original = module._require_driver
    try:
        module._require_driver = lambda: (_ for _ in ()).throw(
            ImportError('pip install "amp-server[postgres]"')
        )
        with pytest.raises(ImportError, match="amp-server\\[postgres\\]"):
            module.PostgresAdapter(dsn="postgresql://unused")
    finally:
        module._require_driver = original


# ---------------------------------------------------------------------------
# What the adapter tells /spec
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_both_backends_report_a_name_their_embedding_and_their_policy(adapter):
    assert adapter.name in {"chroma", "postgres"}
    assert adapter.embedding == {
        "provider": "stub-keywords",
        "dimensions": KeywordEmbedding.dimensions,
    }
    assert adapter.retention_days == RETENTION_DAYS == 30


@pytest.mark.asyncio
async def test_update_accepts_a_model_as_well_as_a_dict(adapter):
    cell = make_cell(owner_id=_OWNER, created_by=_CREATOR, text="before")
    await adapter.save(cell)

    updated = await adapter.update(
        cell.id, MemoryCellUpdate(lifecycle=cell.lifecycle.model_copy())
    )

    assert updated.content.text == "before"
