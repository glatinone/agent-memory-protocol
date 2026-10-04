"""`GET /spec` must not advertise anything the server does not do.

Regression this pins: `/spec` reported `max_cell_size_bytes` while nothing
enforced it, so a client that sized its payloads against the advertised number
could still store a cell far larger. A capability is a claim; this file is where
each one is tied to a behaviour.
"""

from __future__ import annotations

import uuid

import pytest
from conftest import make_cell
from httpx import ASGITransport, AsyncClient

from amp_server.errors import AMPError
from amp_server.limits import MAX_CELL_SIZE_BYTES, cell_size_bytes, enforce_cell_size

_HEADERS = {"X-AMP-Agent-ID": "agent-limits"}


def _body(text: str) -> dict:
    return {
        "type": "semantic",
        "content": {"text": text},
        "identity": {"owner_id": "user-limits", "owner_type": "user"},
    }


async def _client():
    import amp_server.main as main_mod
    from amp_server.lifecycle import LifecycleEngine
    from amp_server.storage.chroma import ChromaAdapter

    main_mod._storage = ChromaAdapter(collection_name=f"test_{uuid.uuid4().hex[:12]}")
    main_mod._lifecycle = LifecycleEngine(main_mod._storage)
    return AsyncClient(
        transport=ASGITransport(app=main_mod.app), base_url="http://test"
    )


# ---------------------------------------------------------------------------
# The number itself
# ---------------------------------------------------------------------------


def test_the_limit_is_exact_at_the_advertised_size():
    """The boundary is inclusive: MAX passes, MAX + 1 does not."""
    overhead = cell_size_bytes(make_cell(text=""))

    at_limit = make_cell(text="x" * (MAX_CELL_SIZE_BYTES - overhead))
    assert cell_size_bytes(at_limit) == MAX_CELL_SIZE_BYTES
    enforce_cell_size(at_limit)  # must not raise

    one_over = make_cell(text="x" * (MAX_CELL_SIZE_BYTES - overhead + 1))
    assert cell_size_bytes(one_over) == MAX_CELL_SIZE_BYTES + 1
    with pytest.raises(AMPError) as raised:
        enforce_cell_size(one_over)
    assert raised.value.status_code == 413
    assert raised.value.code == "CELL_TOO_LARGE"


@pytest.mark.asyncio
async def test_spec_reports_the_maximum_that_is_actually_enforced():
    async with await _client() as client:
        response = await client.get("/amp/v1/spec")

    capabilities = response.json()["capabilities"]
    assert capabilities["max_cell_size_bytes"] == MAX_CELL_SIZE_BYTES


# ---------------------------------------------------------------------------
# Through the API
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_cell_over_the_advertised_maximum_is_refused_and_not_stored():
    async with await _client() as client:
        response = await client.post(
            "/amp/v1/memories", headers=_HEADERS, json=_body("x" * 70_000)
        )

        assert response.status_code == 413
        assert response.json()["error"]["code"] == "CELL_TOO_LARGE"

        # Nothing was written: the check runs before storage is touched.
        listing = await client.get(
            "/amp/v1/memories", headers=_HEADERS, params={"owner_id": "user-limits"}
        )

    assert listing.json()["total"] == 0


@pytest.mark.asyncio
async def test_the_large_cell_is_refused_because_of_the_limit(monkeypatch):
    """Proof that the 413 above comes from the limit and not from something else.

    With the check disabled, the very same request succeeds - so the refusal is
    the limit doing its job, and the guard would notice if enforcement were ever
    dropped.
    """
    monkeypatch.setattr(
        "amp_server.storage.chroma.enforce_cell_size", lambda cell: None
    )

    async with await _client() as client:
        response = await client.post(
            "/amp/v1/memories", headers=_HEADERS, json=_body("x" * 70_000)
        )

    assert response.status_code == 201, (
        "the request should only be refused by the size check"
    )


@pytest.mark.asyncio
async def test_a_large_but_legal_cell_is_still_accepted():
    """The limit must not be so eager that ordinary cells are rejected."""
    async with await _client() as client:
        response = await client.post(
            "/amp/v1/memories", headers=_HEADERS, json=_body("x" * 60_000)
        )

    assert response.status_code == 201


@pytest.mark.asyncio
async def test_a_patch_cannot_grow_a_cell_past_the_limit():
    async with await _client() as client:
        created = await client.post(
            "/amp/v1/memories", headers=_HEADERS, json=_body("small to start")
        )
        assert created.status_code == 201
        memory_id = created.json()["id"]

        grown = await client.patch(
            f"/amp/v1/memories/{memory_id}",
            headers=_HEADERS,
            json={"content": {"text": "x" * 70_000}},
        )
        assert grown.status_code == 413
        assert grown.json()["error"]["code"] == "CELL_TOO_LARGE"

        after = await client.get(f"/amp/v1/memories/{memory_id}", headers=_HEADERS)

    assert after.json()["content"]["text"] == "small to start"


# ---------------------------------------------------------------------------
# The other advertised capabilities
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_manual_run_endpoint_is_a_route_that_exists():
    import amp_server.main as main_mod

    async with await _client() as client:
        response = await client.get("/amp/v1/spec")
        advertised = response.json()["capabilities"]["lifecycle_scheduler"][
            "manual_run_endpoint"
        ]

    assert advertised in main_mod.app.openapi()["paths"], (
        f"/spec advertises {advertised}, which is not a route"
    )


@pytest.mark.asyncio
async def test_spec_reports_the_embedding_provider_in_use():
    """The advertised provider must be the one producing vectors."""
    from amp_server.embeddings import ChromaDefaultEmbeddingProvider

    async with await _client() as client:
        response = await client.get("/amp/v1/spec")

    advertised = response.json()["capabilities"]["embedding"]
    provider = ChromaDefaultEmbeddingProvider()

    assert advertised == {
        "provider": provider.name,
        "dimensions": provider.dimensions,
    }
    # The dimension claim is a measurement, not a constant someone typed.
    assert len(provider.embed(["probe"])[0]) == advertised["dimensions"]


@pytest.mark.asyncio
async def test_the_advertised_storage_backend_is_the_one_in_use():
    import amp_server.main as main_mod

    async with await _client() as client:
        response = await client.get("/amp/v1/spec")

    wired = type(main_mod.get_storage()).__name__.removesuffix("Adapter").lower()
    assert response.json()["capabilities"]["storage_backends"] == [wired]


@pytest.mark.asyncio
async def test_the_advertised_retention_matches_what_purge_enforces():
    """Spec lifecycle.md §5: a purge inside the window must be refused.

    The advertised number is the one the enforcement uses - not a constant that
    happens to be printed next to a separately hard-coded check.
    """
    import amp_server.main as main_mod
    from amp_server.models import LifecycleStatus
    from amp_server.retention import RETENTION_DAYS, RetentionWindowError

    async with await _client() as client:
        advertised = (await client.get("/amp/v1/spec")).json()["capabilities"][
            "retention_days"
        ]

    assert advertised == main_mod.get_storage().retention_days == RETENTION_DAYS

    # And the rule behind the number: a cell deleted now cannot be purged.
    storage = main_mod.get_storage()
    cell = make_cell(status=LifecycleStatus.ARCHIVED, text="advertised retention")
    await storage.save(cell)
    await storage.mark_deleted(cell.id)

    with pytest.raises(RetentionWindowError):
        await storage.purge(cell.id)


@pytest.mark.asyncio
async def test_the_advertised_version_matches_the_health_endpoint():
    async with await _client() as client:
        spec = (await client.get("/amp/v1/spec")).json()
        health = (await client.get("/amp/v1/health")).json()

    assert spec["amp_version"] == health["amp_version"]
