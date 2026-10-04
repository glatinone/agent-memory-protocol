"""The client against a real server, not a mock.

Every other test in this package mocks the transport, and that is exactly why two
bugs lived in this client:

- the async `forget` never archived before deleting. The protocol only permits
  `archived -> deleted`, so it was refused with 409 for every cell a caller would
  actually want to forget. Its test mocked the DELETE and never modelled the
  precondition, so it passed while the method could not work.
- the contract test asserted the client echoed `created_at` on its archiving PATCH,
  which was a workaround for a server-side requirement that no longer exists.

A mock answers whatever the test tells it to. Only a real server can disagree with
it, so these run against one when it is reachable and skip when it is not - the
suite still runs on a laptop with nothing started. `AMP_REQUIRE_LIVE_SERVER=1`
turns that skip into a failure, the way the storage job does with
`AMP_REQUIRE_POSTGRES`, because a suite that skips itself reports green and the
point of the CI job is to prove the client works against a real server.
"""

from __future__ import annotations

import os
import uuid

import pytest

from amp_client import AMPClient, AsyncAMPClient
from amp_client.exceptions import AMPError

DEFAULT_URL = "http://127.0.0.1:8765"
REQUIRE_SERVER = os.environ.get("AMP_REQUIRE_LIVE_SERVER") not in (
    None,
    "",
    "0",
    "false",
)


def owner_id() -> str:
    """A fresh owner per test, so a re-run does not read the previous one's data."""
    return f"user-live-{uuid.uuid4().hex[:10]}"


@pytest.fixture(scope="module")
def server_url() -> str:
    url = os.environ.get("AMP_TEST_URL", DEFAULT_URL)
    if AMPClient(url, agent_id="live-probe").health():
        return url
    if REQUIRE_SERVER:
        pytest.fail(
            f"AMP_REQUIRE_LIVE_SERVER is set but no server answered at {url}: "
            "the client would not have been exercised against a real one"
        )
    pytest.skip(f"no AMP server reachable at {url}; set AMP_TEST_URL to run these")


def client(server_url: str, agent_id: str = "live-agent") -> AMPClient:
    return AMPClient(server_url, agent_id=agent_id)


def async_client(server_url: str, agent_id: str = "live-agent") -> AsyncAMPClient:
    return AsyncAMPClient(server_url, agent_id=agent_id)


# ---------------------------------------------------------------------------
# Round trips
# ---------------------------------------------------------------------------


def test_remember_then_get_memory_returns_the_cell(server_url):
    owner = owner_id()
    stored = client(server_url).remember("User prefers email.", owner_id=owner)

    fetched = client(server_url).get_memory(stored["id"])

    assert fetched["content"]["text"] == "User prefers email."
    assert fetched["identity"]["owner_id"] == owner


def test_reading_bumps_the_access_count(server_url):
    """GET is documented as resetting the decay clock, and it is the only way to."""
    owner = owner_id()
    stored = client(server_url).remember("Read me twice.", owner_id=owner)

    first = client(server_url).get_memory(stored["id"])
    second = client(server_url).get_memory(stored["id"])

    assert second["scoring"]["access_count"] == first["scoring"]["access_count"] + 1


def test_recall_finds_what_remember_stored(server_url):
    owner = owner_id()
    client(server_url).remember("The invoice number is INV-4471.", owner_id=owner)

    hits = client(server_url).recall("invoice number", owner_id=owner)

    assert any("INV-4471" in cell["content"]["text"] for cell in hits)


def test_list_memories_pages_with_offset(server_url):
    owner = owner_id()
    api = client(server_url)
    for index in range(3):
        api.remember(f"paged memory {index}", owner_id=owner)

    first = api.list_memories(owner_id=owner, limit=2)
    second = api.list_memories(owner_id=owner, limit=2, offset=2)

    assert len(first) == 2
    assert {cell["id"] for cell in first} & {cell["id"] for cell in second} == set()


# ---------------------------------------------------------------------------
# The rules, seen from a client
# ---------------------------------------------------------------------------


def test_forget_archives_then_deletes_against_a_real_server(server_url):
    """The order the protocol requires, proven where it is enforced.

    This is the case a mock never modelled: DELETE is only permitted from
    `archived`, so a client that skips the PATCH is refused with 409 for any cell
    a caller would actually want to forget.
    """
    owner = owner_id()
    api = client(server_url)
    stored = api.remember("Delete me properly.", owner_id=owner)

    assert api.forget(stored["id"]) is True

    # Gone: a deleted cell answers 403 to a by-id read, per spec §8.4.
    with pytest.raises(AMPError) as raised:
        api.get_memory(stored["id"])
    assert raised.value.status_code == 403

    assert api.recall("Delete me properly", owner_id=owner) == []


def test_an_agent_the_memory_was_not_shared_with_gets_nothing(server_url):
    owner = owner_id()
    client(server_url, "live-owner").remember(
        "Only billing may read this.", owner_id=owner, readable_by=["live-billing*"]
    )

    allowed = client(server_url, "live-billing-v1").recall(
        "only billing", owner_id=owner
    )
    refused = client(server_url, "live-marketing").recall(
        "only billing", owner_id=owner
    )

    assert len(allowed) == 1
    assert refused == []


def test_an_unknown_cell_surfaces_the_protocol_error_code(server_url):
    """The SDK parses the protocol envelope, so the code has to arrive intact.

    Spec §8.4: the answer is 403 and not 404, whichever the truth is, so a caller
    cannot probe for cells it may not read.
    """
    with pytest.raises(AMPError) as raised:
        client(server_url).get_memory("mem_00000000000000000000000000")

    assert raised.value.status_code == 403
    assert "ACCESS_DENIED" in str(raised.value)


def test_a_rejected_body_surfaces_the_validation_code(server_url):
    """The one error shape holds for a bad request too, and the client reads it."""
    with pytest.raises(AMPError) as raised:
        client(server_url).recall("anything", owner_id="user-live", limit=100000)

    assert raised.value.status_code == 422
    assert "VALIDATION_ERROR" in str(raised.value)


# ---------------------------------------------------------------------------
# The async client, which is the one that was broken
# ---------------------------------------------------------------------------


async def test_async_forget_archives_then_deletes(server_url):
    """The regression this file exists for: async `forget` used to skip the archive."""
    owner = owner_id()
    async with async_client(server_url) as api:
        stored = await api.remember("Async delete me.", owner_id=owner)

        assert await api.forget(stored["id"]) is True

        with pytest.raises(AMPError):
            await api.get_memory(stored["id"])


async def test_async_round_trip(server_url):
    owner = owner_id()
    async with async_client(server_url) as api:
        stored = await api.remember("Async memory.", owner_id=owner)
        fetched = await api.get_memory(stored["id"])
        hits = await api.recall("async memory", owner_id=owner)

    assert fetched["id"] == stored["id"]
    assert any(cell["id"] == stored["id"] for cell in hits)
