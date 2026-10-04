"""The SDK must only speak what the committed contract describes.

The client is hand-written, so it can drift from the API it targets: a renamed
endpoint or a dropped required field would only show up at runtime, against a
real server, in a user's application.

These tests drive the real client through a recording adapter - no source
inspection, the code actually runs - and check two things against
`spec/v0.1.0/openapi.json`:

- every request the client makes lands on a path the contract serves, with a
  method the contract serves it with;
- the body the client posts for a new cell carries the fields the contract marks
  required.

The same check is what would have caught the LangChain integration breaking
silently: it was advertised in the README and had no test at all.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

import pytest
import requests

from amp_client import AMPClient

CONTRACT_PATH = Path(__file__).resolve().parents[3] / "spec" / "v0.1.0" / "openapi.json"

if not CONTRACT_PATH.is_file():  # the SDK also ships standalone, without the repo
    pytest.skip(
        f"API contract not found at {CONTRACT_PATH}; run from a repository clone",
        allow_module_level=True,
    )


def _contract() -> dict:
    with CONTRACT_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def _template_to_regex(template: str) -> re.Pattern[str]:
    """Turn `/memories/{memory_id}` into a pattern that matches a real path."""
    parts = re.split(r"(\{[^}]+\})", template)
    out = ""
    for part in parts:
        out += "[^/]+" if part.startswith("{") else re.escape(part)
    return re.compile(out + "$")


def _ref_of(contract: dict, schema: dict) -> str:
    """Return the $ref a schema points at, through an optional wrapper.

    `MemoryCellUpdate.lifecycle` is `MemoryLifecycle | None`, which serializes as
    an `anyOf` with a null branch rather than a bare `$ref`.
    """
    if "$ref" in schema:
        return schema["$ref"]
    for option in schema.get("anyOf", []):
        if "$ref" in option:
            return option["$ref"]
    raise AssertionError(f"no $ref in {schema}")


def _served_by(contract: dict, method: str, path: str) -> str | None:
    """The contract template that serves this call, or None.

    `/memories/search` also matches the `/memories/{memory_id}` template, so the
    method has to agree as well - that is what tells the two apart.
    """
    lowered = method.lower()
    for template in contract["paths"]:
        if (
            _template_to_regex(template).fullmatch(path)
            and lowered in contract["paths"][template]
        ):
            return template
    return None


def _resolve_ref(contract: dict, ref: str) -> dict:
    node: object = contract
    for step in ref.lstrip("#/").split("/"):
        node = node[step]  # type: ignore[index]
    assert isinstance(node, dict)
    return node


class _RecordingAdapter(requests.adapters.BaseAdapter):
    """Answers every request locally and remembers what the client asked for."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []

    def send(self, request, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(
            (request.method.upper(), urlparse(request.url).path, request.body)
        )
        status, payload = self._reply(
            request.method.upper(), urlparse(request.url).path
        )

        response = requests.Response()
        response.status_code = status
        response._content = json.dumps(payload).encode()
        response.headers["Content-Type"] = "application/json"
        response.encoding = "utf-8"
        response.request = request
        response.url = request.url
        return response

    @staticmethod
    def _reply(method: str, path: str) -> tuple[int, dict]:
        if path == "/amp/v1/health":
            return 200, {"status": "ok", "amp_version": "0.1.0"}
        if path.endswith("/memories/search"):
            return 200, {"results": [], "total": 0, "query": "x"}
        if method == "POST" and path == "/amp/v1/memories":
            return 201, {
                "id": "mem_01J5A3B7K9M2N4P6Q8R0S1T3V5",
                "lifecycle": {"created_at": "2025-01-01T00:00:00Z", "status": "active"},
            }
        if method == "GET" and path == "/amp/v1/memories":
            return 200, {"results": [], "total": 0}
        if method == "GET" and path.startswith("/amp/v1/memories/"):
            return 200, {
                "id": path.rsplit("/", 1)[-1],
                "lifecycle": {"created_at": "2025-01-01T00:00:00Z", "status": "active"},
            }
        if method == "PATCH":
            return 200, {
                "id": path.rsplit("/", 1)[-1],
                "lifecycle": {"status": "archived"},
            }
        if method == "DELETE":
            return 204, {}
        raise AssertionError(f"the client called an unexpected route: {method} {path}")


@pytest.fixture
def recorder() -> tuple[AMPClient, _RecordingAdapter]:
    client = AMPClient("http://test", "agent-contract")
    adapter = _RecordingAdapter()
    client.session.mount("http://", adapter)
    return client, adapter


def _exercise_every_method(recorder) -> None:
    """Call every public method once, so the recorded set is complete."""
    client, _ = recorder
    client.remember("a preference", "user-1")
    client.recall("a preference", "user-1")
    client.list_memories("user-1")
    client.get_memory("mem_01J5A3B7K9M2N4P6Q8R0S1T3V5")
    client.forget("mem_01J5A3B7K9M2N4P6Q8R0S1T3V5")
    client.health()


# ---------------------------------------------------------------------------
# Paths and methods
# ---------------------------------------------------------------------------


def test_every_call_the_client_makes_is_a_path_the_contract_serves(recorder):
    _exercise_every_method(recorder)
    _, adapter = recorder

    contract = _contract()

    unserved = [
        f"{method} {path}"
        for method, path, _ in adapter.calls
        if _served_by(contract, method, path) is None
    ]
    assert not unserved, (
        f"the client calls routes the contract does not serve: {unserved}"
    )


def test_the_exercise_really_covers_the_clients_whole_surface(recorder):
    """Guards the test above from passing because nothing was called."""
    _exercise_every_method(recorder)
    _, adapter = recorder

    contract = _contract()
    templated = {
        (method.lower(), _served_by(contract, method, path))
        for method, path, _ in adapter.calls
    }

    assert templated == {
        ("get", "/amp/v1/health"),
        ("post", "/amp/v1/memories"),
        ("post", "/amp/v1/memories/search"),
        ("get", "/amp/v1/memories"),
        ("get", "/amp/v1/memories/{memory_id}"),
        ("patch", "/amp/v1/memories/{memory_id}"),
        ("delete", "/amp/v1/memories/{memory_id}"),
    }


def test_the_recall_endpoint_is_reached(recorder):
    """A small, explicit guard that search is exercised and not shadowed."""
    client, adapter = recorder
    client.recall("q", "user-1")
    assert ("POST", "/amp/v1/memories/search") in [(m, p) for m, p, _ in adapter.calls]


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


def test_the_create_body_carries_the_contracts_required_fields(recorder):
    client, adapter = recorder
    client.remember("a preference", "user-1")

    contract = _contract()
    schema = contract["paths"]["/amp/v1/memories"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]
    required = set(_resolve_ref(contract, schema["$ref"])["required"])

    body = next(
        json.loads(raw)
        for method, path, raw in adapter.calls
        if method == "POST" and path == "/amp/v1/memories"
    )
    assert required <= set(body), f"create body is missing {required - set(body)}"


def test_the_archiving_patch_maysend_a_partial_lifecycle(recorder):
    """`forget` archives first, and a status alone is what the contract asks for.

    This test used to assert the opposite - that the client echoed `created_at`
    because the lifecycle model required it on write, which is why `forget` did a
    GET first. The server's update model now omits the field, so the assertion
    flips: the contract must not require it and the client must not send it. If
    the server ever requires it again, this is where the SDK finds out.
    """
    client, adapter = recorder
    client.forget("mem_01J5A3B7K9M2N4P6Q8R0S1T3V5")

    contract = _contract()
    update_schema = contract["paths"]["/amp/v1/memories/{memory_id}"]["patch"][
        "requestBody"
    ]["content"]["application/json"]["schema"]
    update_model = _resolve_ref(contract, update_schema["$ref"])
    lifecycle_model = _resolve_ref(
        contract, _ref_of(contract, update_model["properties"]["lifecycle"])
    )
    required = set(lifecycle_model.get("required", []))
    assert required == set(), f"the update model requires {required}"
    assert "created_at" not in lifecycle_model["properties"], (
        "created_at is the anchor the decay formula measures from; it must not be "
        "writable through an update"
    )

    body = next(
        json.loads(raw) for method, _, raw in adapter.calls if method == "PATCH" and raw
    )
    assert body["lifecycle"]["status"] == "archived"
    assert "created_at" not in body["lifecycle"]


def test_every_request_sends_the_agent_identity_header():
    """Spec §8.1: the header is required, and the client is where it comes from."""
    seen: list[str | None] = []

    class _HeaderRecordingAdapter(_RecordingAdapter):
        def send(self, request, **kwargs):  # type: ignore[no-untyped-def]
            seen.append(request.headers.get("X-AMP-Agent-ID"))
            return super().send(request, **kwargs)

    client = AMPClient("http://test", "agent-contract")
    client.session.mount("http://", _HeaderRecordingAdapter())

    client.remember("a preference", "user-1")
    client.recall("a preference", "user-1")
    client.list_memories("user-1")
    client.health()

    assert len(seen) == 4, seen
    assert all(agent == "agent-contract" for agent in seen), seen
