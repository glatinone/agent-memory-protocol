"""API keys: proof of identity, layered on the spec's identity header.

RFC-AMP-001 §6.1 carries agent identity in the `X-AMP-Agent-ID` header and
defines no credential, so the header is an assertion rather than proof. These
tests pin both halves of the arrangement:

- with no key store configured, the header is trusted exactly as the spec
  describes, so the binding does not change for anyone who has not opted in;
- with a store configured, a caller must prove it owns the id it claims - and an
  id supplied in a request body does not count, because that would be the same
  unproven assertion wearing a different hat.
"""

from __future__ import annotations

import json

import pytest
from conftest import install_app_state, make_cell
from httpx import ASGITransport, AsyncClient

from amp_server.auth import ApiKeyStore, digest, load_store, store_from_env

_KEY = "agent-one-secret-key"
_OTHER_KEY = "agent-two-secret-key"
_HEADERS = {"X-AMP-Agent-ID": "agent-one"}


def _install_app(store: ApiKeyStore | None = None) -> None:
    """Fresh state with this file's one difference: the key store."""
    install_app_state(api_key_store=store)


def _store(monkeypatch, tmp_path, keys: dict[str, str]) -> ApiKeyStore:
    """Write a key store file and install it on the app, as the lifespan would."""
    path = tmp_path / "api-keys.json"
    path.write_text(
        json.dumps({agent_id: digest(key) for agent_id, key in keys.items()}),
        encoding="utf-8",
    )
    monkeypatch.setenv("AMP_API_KEYS_FILE", str(path))

    store = store_from_env()
    assert store is not None
    _install_app(store)
    return store


@pytest.fixture(autouse=True)
def _no_keys_by_default():
    """Every test starts from "this deployment has no keys".

    Installed on the module, not read from the environment, so a stray
    AMP_API_KEYS_FILE in a developer's shell cannot change what these assert.
    """
    import amp_server.main as main_mod

    main_mod._api_key_store = None
    yield
    main_mod._api_key_store = None


async def _client() -> AsyncClient:
    import amp_server.main as main_mod

    return AsyncClient(
        transport=ASGITransport(app=main_mod.app), base_url="http://test"
    )


def _body() -> dict:
    return {
        "type": "semantic",
        "content": {"text": "authenticated memory"},
        "identity": {"owner_id": "user-auth", "owner_type": "user"},
    }


# ---------------------------------------------------------------------------
# The store itself
# ---------------------------------------------------------------------------


def test_a_digest_is_sha256_and_never_the_key():
    value = digest(_KEY)

    assert value.startswith("sha256:")
    assert len(value) == len("sha256:") + 64
    assert _KEY not in value


def test_verify_accepts_the_registered_key_only():
    store = ApiKeyStore(digests={"agent-one": digest(_KEY)})

    assert store.verify("agent-one", _KEY) is True
    assert store.verify("agent-one", _OTHER_KEY) is False
    assert store.verify("agent-one", "") is False


def test_verify_rejects_an_unknown_agent_without_raising():
    """A key for an agent that does not exist is simply not valid."""
    store = ApiKeyStore(digests={"agent-one": digest(_KEY)})

    assert store.verify("agent-nobody", _OTHER_KEY) is False
    assert store.verify("agent-nobody", "") is False


def test_loading_reports_the_file_it_cannot_read(tmp_path):
    missing = tmp_path / "nope.json"

    with pytest.raises(ValueError, match="does not exist"):
        load_store(missing)


def test_loading_refuses_a_raw_key_in_the_store(tmp_path):
    """The file holds digests; a pasted key would be a leak waiting to happen."""
    path = tmp_path / "api-keys.json"
    path.write_text(json.dumps({"agent-one": _KEY}), encoding="utf-8")

    with pytest.raises(ValueError, match="digest, not a raw key"):
        load_store(path)


def test_loading_refuses_a_malformed_store(tmp_path):
    """Half a store is worse than none: the parsed entries would be enforced."""
    path = tmp_path / "api-keys.json"

    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        load_store(path)

    path.write_text(json.dumps(["agent-one"]), encoding="utf-8")
    with pytest.raises(ValueError, match="must be a JSON object"):
        load_store(path)

    path.write_text(json.dumps({"agent-one": "sha256:short"}), encoding="utf-8")
    with pytest.raises(ValueError, match="not a sha256 digest"):
        load_store(path)

    path.write_text(json.dumps({}), encoding="utf-8")
    with pytest.raises(ValueError, match="contains no agents"):
        load_store(path)


def test_no_file_means_no_keys(monkeypatch):
    monkeypatch.delenv("AMP_API_KEYS_FILE", raising=False)
    assert store_from_env() is None


# ---------------------------------------------------------------------------
# Without a store: the spec's binding, unchanged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_header_alone_still_works_without_a_store():
    _install_app()

    async with await _client() as client:
        created = await client.post("/amp/v1/memories", json=_body(), headers=_HEADERS)

    assert created.status_code == 201


@pytest.mark.asyncio
async def test_without_a_store_a_body_supplied_identity_is_still_accepted():
    """The `created_by` fallback is the documented default, not a hole.

    It is only reachable when no key store is configured; the test below pins the
    other half.
    """
    _install_app()
    body = _body()
    body["identity"]["created_by"] = "agent-from-body"

    async with await _client() as client:
        created = await client.post("/amp/v1/memories", json=body)

    assert created.status_code == 201
    assert created.json()["identity"]["created_by"] == "agent-from-body"


# ---------------------------------------------------------------------------
# With a store: proof required
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_request_without_a_key_is_refused(monkeypatch, tmp_path):
    _store(monkeypatch, tmp_path, {"agent-one": _KEY})

    async with await _client() as client:
        response = await client.post("/amp/v1/memories", json=_body(), headers=_HEADERS)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


@pytest.mark.asyncio
async def test_a_key_for_another_agent_is_refused(monkeypatch, tmp_path):
    _store(monkeypatch, tmp_path, {"agent-one": _KEY, "agent-two": _OTHER_KEY})

    async with await _client() as client:
        response = await client.post(
            "/amp/v1/memories",
            json=_body(),
            headers={**_HEADERS, "X-AMP-API-Key": _OTHER_KEY},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_an_unknown_agent_answers_like_a_wrong_key(monkeypatch, tmp_path):
    """Same response either way, so the route cannot enumerate agent ids."""
    _store(monkeypatch, tmp_path, {"agent-one": _KEY})

    async with await _client() as client:
        unknown = await client.post(
            "/amp/v1/memories",
            json=_body(),
            headers={"X-AMP-Agent-ID": "agent-nobody", "X-AMP-API-Key": _KEY},
        )
        wrong = await client.post(
            "/amp/v1/memories",
            json=_body(),
            headers={**_HEADERS, "X-AMP-API-Key": "not-the-key"},
        )

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


@pytest.mark.asyncio
async def test_the_right_key_gets_through(monkeypatch, tmp_path):
    _store(monkeypatch, tmp_path, {"agent-one": _KEY})

    async with await _client() as client:
        created = await client.post(
            "/amp/v1/memories",
            json=_body(),
            headers={**_HEADERS, "X-AMP-API-Key": _KEY},
        )
        fetched = await client.get(
            f"/amp/v1/memories/{created.json()['id']}",
            headers={**_HEADERS, "X-AMP-API-Key": _KEY},
        )

    assert created.status_code == 201
    assert fetched.status_code == 200


@pytest.mark.asyncio
async def test_a_body_supplied_identity_cannot_bypass_a_configured_store(
    monkeypatch, tmp_path
):
    """The fallback would otherwise let any caller create as any agent."""
    _store(monkeypatch, tmp_path, {"agent-one": _KEY})
    body = _body()
    body["identity"]["created_by"] = "agent-impersonated"

    async with await _client() as client:
        response = await client.post("/amp/v1/memories", json=body)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


@pytest.mark.asyncio
async def test_health_and_spec_stay_open(monkeypatch, tmp_path):
    """Operators and clients read these before they have a key."""
    _store(monkeypatch, tmp_path, {"agent-one": _KEY})

    async with await _client() as client:
        health = await client.get("/amp/v1/health")
        spec = await client.get("/amp/v1/spec")

    assert health.status_code == 200
    assert spec.status_code == 200


@pytest.mark.asyncio
async def test_every_agent_route_is_behind_the_same_gate(monkeypatch, tmp_path):
    """A route that resolves an agent id without proving it would be the bug.

    Written as a sweep rather than one case per route so a route added later
    without the dependency fails here instead of shipping unverified.
    """
    _store(monkeypatch, tmp_path, {"agent-one": _KEY})
    cell = make_cell(created_by="agent-one", text="guarded")
    import amp_server.main as main_mod

    await main_mod.get_storage().save(cell)

    calls = [
        ("post", "/amp/v1/memories", {"json": _body()}),
        ("get", f"/amp/v1/memories/{cell.id}", {}),
        ("patch", f"/amp/v1/memories/{cell.id}", {"json": {"content": {"text": "x"}}}),
        ("delete", f"/amp/v1/memories/{cell.id}", {}),
        ("get", "/amp/v1/memories?limit=5", {}),
        ("get", "/amp/v1/memories/query?limit=5", {}),
        ("post", "/amp/v1/memories/search", {"json": {"query": "guarded"}}),
    ]

    async with await _client() as client:
        for method, url, kwargs in calls:
            response = await getattr(client, method)(url, headers=_HEADERS, **kwargs)
            assert response.status_code == 401, (
                f"{method.upper()} {url} answered {response.status_code} without a key"
            )


@pytest.mark.asyncio
async def test_spec_says_whether_a_key_is_needed(monkeypatch, tmp_path):
    """A client should learn it needs a key before a call fails with 401."""
    _install_app()
    async with await _client() as client:
        without = (await client.get("/amp/v1/spec")).json()

    _store(monkeypatch, tmp_path, {"agent-one": _KEY})
    async with await _client() as client:
        with_keys = (await client.get("/amp/v1/spec")).json()

    assert without["capabilities"]["api_keys_required"] is False
    assert with_keys["capabilities"]["api_keys_required"] is True
