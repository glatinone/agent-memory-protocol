"""One error envelope on every endpoint.

Regression this pins: `PATCH /memories/{id}` used to answer a conflict with
`{"detail": ...}` while `DELETE` answered with `{"error": {...}}`. Both SDKs
read `body.error.code` / `body.error.message`, so the PATCH conflict degraded
to a generic "HTTP error 409" in a client. Every protocol error now comes from
`amp_server.errors.AMPError`, and these tests fix the wire contract so a future
inline `JSONResponse` cannot quietly introduce a second shape.

These tests used to build their own client against the bare app, which meant they
reached whatever storage a *previous test file* had left on the module - so half of
them failed when this file ran on its own. They take `app_client` from conftest now,
which installs state this test owns.
"""

from __future__ import annotations

import pytest

from amp_server.errors import (
    AMPError,
    access_denied,
    admin_disabled,
    invalid_transition,
    missing_agent_id,
)

_HEADERS = {"X-AMP-Agent-ID": "agent_error_shape"}


def _minimal_body(text: str = "error shape probe") -> dict:
    return {
        "type": "semantic",
        "content": {"text": text},
        "identity": {"owner_id": "user_error_shape", "owner_type": "user"},
    }


def _assert_error_envelope(body: dict, expected_code: str) -> None:
    """The whole contract: one top-level key, three documented fields."""
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details"}
    assert body["error"]["code"] == expected_code
    assert body["error"]["message"]


@pytest.mark.asyncio
async def test_missing_agent_id_uses_the_error_envelope(app_client):
    resp = await app_client.post("/amp/v1/memories", json=_minimal_body())

    assert resp.status_code == 401
    _assert_error_envelope(resp.json(), "MISSING_AGENT_ID")


@pytest.mark.asyncio
async def test_access_denied_uses_the_error_envelope(app_client):
    resp = await app_client.get("/amp/v1/memories/does-not-exist", headers=_HEADERS)

    assert resp.status_code == 403
    _assert_error_envelope(resp.json(), "ACCESS_DENIED")


@pytest.mark.asyncio
async def test_invalid_transition_uses_the_error_envelope(app_client):
    created = await app_client.post(
        "/amp/v1/memories", headers=_HEADERS, json=_minimal_body()
    )
    assert created.status_code == 201

    resp = await app_client.delete(
        f"/amp/v1/memories/{created.json()['id']}", headers=_HEADERS
    )

    assert resp.status_code == 409
    _assert_error_envelope(resp.json(), "INVALID_TRANSITION")


@pytest.mark.asyncio
async def test_a_rejected_body_uses_the_error_envelope(app_client):
    """The framework's own validation error is part of the wire contract too.

    A malformed body never reaches a route, so it never passed through AMPError -
    it answered with FastAPI's `{"detail": [...]}` while everything else used
    `{"error": {...}}`. Both SDKs read `error.code`, so a caller that sent a bad
    field got a generic "HTTP error 422" and no idea which field was wrong.
    """
    resp = await app_client.post(
        "/amp/v1/memories", headers=_HEADERS, json={"type": "semantic"}
    )

    assert resp.status_code == 422
    _assert_error_envelope(resp.json(), "VALIDATION_ERROR")
    assert "detail" not in resp.json()


@pytest.mark.asyncio
async def test_a_rejected_body_names_the_field_that_was_wrong(app_client):
    """`details` carries the field errors, which is what `details` is for."""
    resp = await app_client.post(
        "/amp/v1/memories", headers=_HEADERS, json={"type": "semantic"}
    )

    errors = resp.json()["error"]["details"]["errors"]
    locations = {".".join(str(part) for part in error["loc"]) for error in errors}
    assert "body.content" in locations
    assert "body.identity" in locations


@pytest.mark.asyncio
async def test_an_out_of_range_page_size_uses_the_error_envelope(app_client):
    """Every route that validates a parameter answers the same way."""
    resp = await app_client.get("/amp/v1/memories?limit=1000000", headers=_HEADERS)

    assert resp.status_code == 422
    _assert_error_envelope(resp.json(), "VALIDATION_ERROR")


def test_every_error_helper_serialises_to_the_same_envelope():
    """The helpers are the only source of protocol errors, so they must agree."""
    cases = [
        (missing_agent_id(), 401, "MISSING_AGENT_ID"),
        (access_denied(), 403, "ACCESS_DENIED"),
        (admin_disabled(), 403, "ADMIN_DISABLED"),
        (invalid_transition("nope"), 409, "INVALID_TRANSITION"),
    ]
    for exc, expected_status, expected_code in cases:
        assert isinstance(exc, AMPError)
        assert exc.status_code == expected_status
        _assert_error_envelope(exc.to_response(), expected_code)
