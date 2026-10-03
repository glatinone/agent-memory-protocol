"""The committed API contract must describe the server, including its errors.

`spec/v0.1.0/openapi.json` is generated from the FastAPI app and committed, so a
change to the API surface shows up as a reviewable diff instead of only in the
runtime. Writing this test found two ways the document was wrong:

- it advertised `200` for `DELETE /memories/{id}`, which answers `204`; the route
  now declares its status code;
- it documented no error response at all, so a generated client had nothing to
  type its error handling against, even though the error envelope is fixed by the
  protocol. The routes now declare the codes they can return.

The whole document is deliberately not compared byte for byte: its serialization
depends on the installed FastAPI version, so that would turn a dependency bump
into a red build. What is compared is the part that *is* the contract - which
paths exist with which methods. The declared codes are guarded by targeted
assertions.

Regenerate after an intentional API change:

    cd server && python -c "import json; from amp_server.main import app; \\
        json.dump(app.openapi(), open('../spec/v0.1.0/openapi.json', 'w'), \\
                  indent=2, sort_keys=True)"
"""

from __future__ import annotations

import json
from pathlib import Path

from amp_server.main import AMP_VERSION, app

CONTRACT_PATH = Path(__file__).resolve().parents[2] / "spec" / "v0.1.0" / "openapi.json"


def _contract() -> dict:
    with CONTRACT_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def _surface(schema: dict) -> dict[str, set[str]]:
    """Map every path to the set of HTTP methods it serves."""
    return {
        path: {method.lower() for method in operations}
        for path, operations in schema["paths"].items()
    }


def _codes(schema: dict, path: str, method: str) -> set[str]:
    return set(schema["paths"][path][method]["responses"])


# ---------------------------------------------------------------------------
# The file itself
# ---------------------------------------------------------------------------


def test_the_contract_is_committed_next_to_the_spec():
    assert CONTRACT_PATH.is_file(), f"contract not found at {CONTRACT_PATH}"


def test_the_contract_covers_the_same_paths_and_methods_as_the_app():
    committed = _surface(_contract())
    live = _surface(app.openapi())

    assert committed == live, {
        "only in the committed contract": {
            p: sorted(m - live.get(p, set())) for p, m in committed.items()
        },
        "only in the live app": {
            p: sorted(m - committed.get(p, set())) for p, m in live.items()
        },
    }


def test_the_contract_advertises_the_server_version():
    assert _contract()["info"]["version"] == AMP_VERSION


def test_every_route_lives_under_the_api_prefix():
    assert all(path.startswith("/amp/v1/") for path in _contract()["paths"])


# ---------------------------------------------------------------------------
# The codes the protocol fixes
# ---------------------------------------------------------------------------


def test_delete_documents_its_204_success():
    """Regression: the contract said 200 while the server answered 204."""
    assert "204" in _codes(_contract(), "/amp/v1/memories/{memory_id}", "delete")
    assert "200" not in _codes(_contract(), "/amp/v1/memories/{memory_id}", "delete")


def test_routes_that_require_an_agent_identity_document_401():
    """Spec §8.1: the identity header is required on these."""
    contract = _contract()
    expected = {
        ("/amp/v1/memories", "get"),
        ("/amp/v1/memories", "post"),
        ("/amp/v1/memories/query", "get"),
        ("/amp/v1/memories/search", "post"),
        ("/amp/v1/memories/{memory_id}", "get"),
        ("/amp/v1/memories/{memory_id}", "patch"),
        ("/amp/v1/memories/{memory_id}", "delete"),
    }
    missing = [route for route in expected if "401" not in _codes(contract, *route)]
    assert not missing, f"routes missing a documented 401: {missing}"


def test_routes_that_can_deny_access_document_403():
    contract = _contract()
    expected = {
        ("/amp/v1/memories/{memory_id}", "get"),
        ("/amp/v1/memories/{memory_id}", "patch"),
        ("/amp/v1/memories/{memory_id}", "delete"),
    }
    missing = [route for route in expected if "403" not in _codes(contract, *route)]
    assert not missing, f"routes missing a documented 403: {missing}"


def test_the_writes_that_can_conflict_document_409():
    """Spec §2: a refused transition is 409 INVALID_TRANSITION."""
    contract = _contract()
    expected = {
        ("/amp/v1/memories/{memory_id}", "patch"),
        ("/amp/v1/memories/{memory_id}", "delete"),
    }
    missing = [route for route in expected if "409" not in _codes(contract, *route)]
    assert not missing, f"routes missing a documented 409: {missing}"


def test_the_error_envelope_is_documented_as_a_schema():
    """The envelope is part of the protocol, so the contract must carry it."""
    schemas = _contract()["components"]["schemas"]
    assert "ErrorResponse" in schemas
    assert set(schemas["ErrorDetail"]["properties"]) == {"code", "message", "details"}


def test_a_documented_error_response_points_at_that_schema():
    contract = _contract()
    response = contract["paths"]["/amp/v1/memories/{memory_id}"]["patch"]["responses"]
    assert response["409"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }
