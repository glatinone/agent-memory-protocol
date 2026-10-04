"""The lifecycle transition table from spec/v0.1.0/lifecycle.md §2.

Regression this pins: `StorageAdapter.update()` applied whatever status it was
handed. `PATCH /memories/{id}` could therefore jump a cell straight to
`deleted`, bypassing the archival precondition and the DELETE semantics, and an
`archived` cell could be pushed back to `active` even though §2 says that is not
permitted. The conformance suite under conformance/ found both.
"""

from __future__ import annotations

import uuid

import pytest
from conftest import make_cell

from amp_server.lifecycle import check_status_transition
from amp_server.models import (
    LifecycleStatus,
    MemoryCellUpdate,
    MemoryLifecycleUpdate,
)
from amp_server.storage.base import InvalidTransitionError

# ---------------------------------------------------------------------------
# The rule itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("current", "target"),
    [
        # Permitted: the DELETE flow archives first, and a stale cell whose
        # score recovers is brought back to active.
        (LifecycleStatus.ACTIVE, LifecycleStatus.ARCHIVED),
        (LifecycleStatus.STALE, LifecycleStatus.ARCHIVED),
        (LifecycleStatus.STALE, LifecycleStatus.ACTIVE),
        (LifecycleStatus.ACTIVE, LifecycleStatus.STALE),
        (LifecycleStatus.ACTIVE, LifecycleStatus.ACTIVE),
    ],
)
def test_permitted_transitions_do_not_raise(current, target):
    check_status_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        # §2: archived may not return to active or stale.
        (LifecycleStatus.ARCHIVED, LifecycleStatus.ACTIVE),
        (LifecycleStatus.ARCHIVED, LifecycleStatus.STALE),
        # §2: use DELETE, not a write, to reach deleted.
        (LifecycleStatus.ACTIVE, LifecycleStatus.DELETED),
        (LifecycleStatus.STALE, LifecycleStatus.DELETED),
        (LifecycleStatus.ARCHIVED, LifecycleStatus.DELETED),
        # deleted is terminal.
        (LifecycleStatus.DELETED, LifecycleStatus.ACTIVE),
        (LifecycleStatus.DELETED, LifecycleStatus.ARCHIVED),
    ],
)
def test_forbidden_transitions_raise(current, target):
    with pytest.raises(InvalidTransitionError):
        check_status_transition(current, target)


# ---------------------------------------------------------------------------
# Through storage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_storage_update_refuses_to_reach_deleted(storage):
    cell = make_cell(status=LifecycleStatus.ACTIVE)
    await storage.save(cell)

    update = MemoryCellUpdate(
        lifecycle=MemoryLifecycleUpdate(status=LifecycleStatus.DELETED)
    )
    with pytest.raises(InvalidTransitionError):
        await storage.update(cell.id, update)

    # And the cell is untouched by the refused write.
    unchanged = await storage._get_raw(cell.id)
    assert unchanged.lifecycle.status is LifecycleStatus.ACTIVE


@pytest.mark.asyncio
async def test_storage_update_refuses_to_unarchive(storage):
    cell = make_cell(status=LifecycleStatus.ARCHIVED)
    await storage.save(cell)

    update = MemoryCellUpdate(
        lifecycle=MemoryLifecycleUpdate(status=LifecycleStatus.ACTIVE)
    )
    with pytest.raises(InvalidTransitionError):
        await storage.update(cell.id, update)


@pytest.mark.asyncio
async def test_storage_update_accepts_the_archiving_delete_flow(storage):
    """The path DELETE depends on must keep working."""
    cell = make_cell(status=LifecycleStatus.ACTIVE)
    await storage.save(cell)

    update = MemoryCellUpdate(
        lifecycle=MemoryLifecycleUpdate(status=LifecycleStatus.ARCHIVED)
    )
    updated = await storage.update(cell.id, update)
    assert updated.lifecycle.status is LifecycleStatus.ARCHIVED

    # ...and then the cell can actually be deleted.
    await storage.mark_deleted(cell.id)
    assert (await storage._get_raw(cell.id)).lifecycle.status is LifecycleStatus.DELETED


@pytest.mark.asyncio
async def test_storage_update_rejects_an_unknown_status_from_a_raw_dict(storage):
    """The MCP tools pass dicts; an unknown value is a 409, not a 500."""
    cell = make_cell(status=LifecycleStatus.ACTIVE)
    await storage.save(cell)

    with pytest.raises(InvalidTransitionError):
        await storage.update(cell.id, {"lifecycle": {"status": "expired"}})


# ---------------------------------------------------------------------------
# Through the API
# ---------------------------------------------------------------------------

_HEADERS = {"X-AMP-Agent-ID": "agent-transitions"}


async def _create(client) -> dict:
    response = await client.post(
        "/amp/v1/memories",
        headers=_HEADERS,
        json={
            "type": "semantic",
            "content": {"text": "transition probe"},
            "identity": {
                "owner_id": f"user-{uuid.uuid4().hex[:8]}",
                "owner_type": "user",
            },
        },
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
async def test_patch_to_deleted_is_409(app_client):
    cell = await _create(app_client)
    response = await app_client.patch(
        f"/amp/v1/memories/{cell['id']}",
        headers=_HEADERS,
        json={"lifecycle": {"status": "deleted"}},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_TRANSITION"


@pytest.mark.asyncio
async def test_archived_cell_cannot_be_patched_back_to_active(app_client):
    cell = await _create(app_client)

    archived = await app_client.patch(
        f"/amp/v1/memories/{cell['id']}",
        headers=_HEADERS,
        json={"lifecycle": {"status": "archived"}},
    )
    assert archived.status_code == 200

    resurrect = await app_client.patch(
        f"/amp/v1/memories/{cell['id']}",
        headers=_HEADERS,
        json={"lifecycle": {"status": "active"}},
    )

    assert resurrect.status_code == 409
    assert resurrect.json()["error"]["code"] == "INVALID_TRANSITION"


@pytest.mark.asyncio
async def test_a_deleted_cell_is_403_not_409(app_client):
    """§8.4 still wins: a deleted cell is invisible, not explained."""
    cell = await _create(app_client)

    # Archive then delete through the documented route, one request each: no
    # reading the cell first to echo `created_at` back.
    await app_client.patch(
        f"/amp/v1/memories/{cell['id']}",
        headers=_HEADERS,
        json={"lifecycle": {"status": "archived"}},
    )
    deleted = await app_client.delete(
        f"/amp/v1/memories/{cell['id']}", headers=_HEADERS
    )
    assert deleted.status_code == 204

    response = await app_client.patch(
        f"/amp/v1/memories/{cell['id']}",
        headers=_HEADERS,
        json={"content": {"text": "still here?"}},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ACCESS_DENIED"
