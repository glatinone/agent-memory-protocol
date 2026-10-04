"""Listing pages: what the caller sees, not what the store happens to hold.

Two things are pinned here. The page size counts cells the caller may *read*, not
cells examined - the store-level page used to be applied before the access filter,
so a page could come back short while readable cells sat just past it, and the
caller could not tell that from "that is all". And the response says what it did:
`returned`, `has_more`, and the window it used, instead of a `total` that was the
size of the page it had just handed over.
"""

from __future__ import annotations

import uuid

import pytest
from conftest import make_cell
from httpx import ASGITransport, AsyncClient

from amp_server.models import LifecycleStatus
from amp_server.paging import MAX_PAGE_SIZE

_OWNER = "user-paging"
_READER = "agent-paging-reader"
_STRANGER = "agent-paging-stranger"


def _install_app() -> None:
    import amp_server.main as main_mod
    from amp_server.lifecycle import LifecycleEngine
    from amp_server.storage.chroma import ChromaAdapter

    main_mod._storage = ChromaAdapter(collection_name=f"test_{uuid.uuid4().hex[:12]}")
    main_mod._lifecycle = LifecycleEngine(main_mod._storage)
    main_mod._api_key_store = None


async def _client() -> AsyncClient:
    import amp_server.main as main_mod

    return AsyncClient(
        transport=ASGITransport(app=main_mod.app), base_url="http://test"
    )


async def _seed(count: int, *, readable_by: list[str] | None = None) -> list[str]:
    """Store `count` cells for `_OWNER` and return their ids in insertion order."""
    import amp_server.main as main_mod

    ids = []
    for index in range(count):
        cell = make_cell(
            owner_id=_OWNER,
            created_by=_OWNER,
            text=f"page cell {index}",
            readable_by=readable_by or [],
        )
        await main_mod.get_storage().save(cell)
        ids.append(cell.id)
    return ids


def _headers(agent_id: str = _READER) -> dict[str, str]:
    return {"X-AMP-Agent-ID": agent_id}


@pytest.mark.asyncio
async def test_a_page_reports_what_it_returned_and_whether_more_follows():
    _install_app()
    await _seed(3, readable_by=[_READER])

    async with await _client() as client:
        first = (
            await client.get("/amp/v1/memories?limit=2", headers=_headers())
        ).json()
        second = (
            await client.get("/amp/v1/memories?limit=2&offset=2", headers=_headers())
        ).json()

    assert first["returned"] == 2
    assert first["has_more"] is True
    assert second["returned"] == 1
    assert second["has_more"] is False
    assert second["offset"] == 2
    assert second["limit"] == 2


@pytest.mark.asyncio
async def test_pages_do_not_overlap_and_cover_everything():
    _install_app()
    stored = await _seed(5, readable_by=[_READER])

    seen: list[str] = []
    async with await _client() as client:
        offset = 0
        while True:
            page = (
                await client.get(
                    f"/amp/v1/memories?limit=2&offset={offset}", headers=_headers()
                )
            ).json()
            seen.extend(cell["id"] for cell in page["results"])
            if not page["has_more"]:
                break
            offset += page["returned"]

    assert sorted(seen) == sorted(stored)
    assert len(seen) == len(set(seen)), "a cell appeared on two pages"


@pytest.mark.asyncio
async def test_the_limit_counts_cells_the_caller_may_read():
    """The bug this replaced: cells examined were counted, not cells readable.

    Four unreadable cells sit in front of three readable ones. A page of three
    must be three readable cells with `has_more` false - the old store-level
    limit would have examined only the first three candidates and returned none.
    """
    _install_app()
    await _seed(4, readable_by=[_STRANGER])
    readable = await _seed(3, readable_by=[_READER])

    async with await _client() as client:
        page = (await client.get("/amp/v1/memories?limit=3", headers=_headers())).json()

    assert page["returned"] == 3
    assert page["has_more"] is False
    assert {cell["id"] for cell in page["results"]} == set(readable)


@pytest.mark.asyncio
async def test_offset_past_the_end_is_empty_and_says_so():
    _install_app()
    await _seed(2, readable_by=[_READER])

    async with await _client() as client:
        page = (
            await client.get("/amp/v1/memories?offset=50", headers=_headers())
        ).json()

    assert page["results"] == []
    assert page["returned"] == 0
    assert page["has_more"] is False


@pytest.mark.asyncio
async def test_a_cell_the_caller_cannot_read_never_shows_up():
    _install_app()
    await _seed(3, readable_by=[_STRANGER])

    async with await _client() as client:
        page = (await client.get("/amp/v1/memories", headers=_headers())).json()

    assert page["results"] == []


@pytest.mark.asyncio
async def test_deleted_cells_are_not_listed_by_default():
    _install_app()
    import amp_server.main as main_mod

    cell = make_cell(
        owner_id=_OWNER,
        created_by=_OWNER,
        text="archived and deleted",
        readable_by=[_READER],
        status=LifecycleStatus.ARCHIVED,
    )
    await main_mod.get_storage().save(cell)
    await main_mod.get_storage().mark_deleted(cell.id)
    await _seed(1, readable_by=[_READER])

    async with await _client() as client:
        page = (await client.get("/amp/v1/memories", headers=_headers())).json()

    assert page["returned"] == 1
    assert cell.id not in {item["id"] for item in page["results"]}


@pytest.mark.asyncio
async def test_the_page_size_is_bounded_on_both_ends():
    """An unbounded limit is a request for the whole store."""
    _install_app()
    await _seed(1, readable_by=[_READER])

    async with await _client() as client:
        too_big = await client.get(
            f"/amp/v1/memories?limit={MAX_PAGE_SIZE + 1}", headers=_headers()
        )
        zero = await client.get("/amp/v1/memories?limit=0", headers=_headers())
        negative_offset = await client.get(
            "/amp/v1/memories?offset=-1", headers=_headers()
        )

    assert too_big.status_code == 422
    assert zero.status_code == 422
    assert negative_offset.status_code == 422


@pytest.mark.asyncio
async def test_the_query_alias_pages_the_same_way():
    _install_app()
    await _seed(3, readable_by=[_READER])

    async with await _client() as client:
        listed = (
            await client.get("/amp/v1/memories?limit=1", headers=_headers())
        ).json()
        queried = (
            await client.get("/amp/v1/memories/query?limit=1", headers=_headers())
        ).json()

    assert listed["results"] == queried["results"]
    assert queried["has_more"] is True


@pytest.mark.asyncio
async def test_spec_advertises_the_page_ceiling():
    _install_app()

    async with await _client() as client:
        capabilities = (await client.get("/amp/v1/spec")).json()["capabilities"]

    assert capabilities["max_page_size"] == MAX_PAGE_SIZE
    assert MAX_PAGE_SIZE >= 1
