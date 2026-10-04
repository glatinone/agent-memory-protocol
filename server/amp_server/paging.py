"""Paging over the cells an agent is allowed to read.

`readable_by` holds patterns rather than ids, so the access rule cannot be pushed
into the storage query - it is applied here, over a scan of candidates. That is
the whole reason this module exists rather than the route passing `limit` and
`offset` straight through:

Applying the page size in the store counted cells *examined*, not cells the
caller may read. A page could therefore come back short while more readable cells
sat past the store-level limit, and the caller had no way to tell that from "that
is all there is". Here `limit` counts cells the caller may read, and `has_more`
answers whether the next page holds anything.
"""

from __future__ import annotations

from amp_server.access_control import check_read_access
from amp_server.models import (
    MAX_PAGE_SIZE,
    LifecycleStatus,
    MemoryCell,
    MemoryType,
)
from amp_server.storage.base import StorageAdapter

__all__ = ["DEFAULT_PAGE_SIZE", "MAX_PAGE_SIZE", "SCAN_CEILING", "readable_page"]

#: The page size when the caller does not choose one.
DEFAULT_PAGE_SIZE = 20
#: How many candidates one request may examine. A filter that matches almost
#: nothing readable would otherwise scan the whole store on every call.
SCAN_CEILING = 5000
#: Candidates fetched per store call. One number, so the cost of a page is the
#: same shape whatever the page size.
_SCAN_BATCH = 100


async def readable_page(
    storage: StorageAdapter,
    *,
    agent_id: str,
    limit: int,
    offset: int = 0,
    owner_id: str | None = None,
    types: list[MemoryType] | None = None,
    status: list[LifecycleStatus] | None = None,
) -> tuple[list[MemoryCell], bool]:
    """The `offset`-th page of `limit` readable cells, and whether more follow.

    `offset` indexes the readable stream - what the caller can see - not the raw
    store, so page 2 is page 2 of the caller's view and stays coherent as other
    cells are written or hidden from them.

    Scans at most `SCAN_CEILING` candidates. Hitting the ceiling reports
    `has_more` from what was found rather than pretending the store ended; the
    ceiling exists to bound a hostile or nonsensical filter, and a caller who
    reaches it has a filter matching almost nothing.
    """
    collected: list[MemoryCell] = []
    skipped = 0
    examined = 0
    store_offset = 0

    while examined < SCAN_CEILING:
        batch = await storage.query(
            owner_id=owner_id,
            types=types,
            status=status,
            limit=_SCAN_BATCH,
            offset=store_offset,
        )
        if not batch:
            break

        store_offset += len(batch)
        examined += len(batch)

        for cell in batch:
            if not check_read_access(cell, agent_id):
                continue
            if skipped < offset:
                skipped += 1
                continue
            collected.append(cell)
            if len(collected) > limit:
                # One past the page: that is what `has_more` means, and it is
                # cheaper than an existence query the store cannot answer anyway.
                return collected[:limit], True

        if len(batch) < _SCAN_BATCH:
            break

    return collected, False
