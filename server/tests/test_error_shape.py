"""One error envelope on every endpoint.

Regression this pins: `PATCH /memories/{id}` used to answer a conflict with
`{"detail": ...}` while `DELETE` answered with `{"error": {...}}`. Both SDKs
read `body.error.code` / `body.error.message`, so the PATCH conflict degraded
to a generic "HTTP error 409" in a client. Every protocol error now comes from
`amp_server.errors.AMPError`, and these tests fix the wire contract so a future
inline `JSONResponse` cannot quietly introduce a second shape.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

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
async def test_missing_agent_id_uses_the_error_envelope():
    from amp_server.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/amp/v1/memories", json=_minimal_body())

    assert resp.status_code == 401
    _assert_error_envelope(resp.json(), "MISSING_AGENT_ID")


@pytest.mark.asyncio
async def test_access_denied_uses_the_error_envelope():
    from amp_server.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/amp/v1/memories/does-not-exist", headers=_HEADERS)

    assert resp.status_code == 403
    _assert_error_envelope(resp.json(), "ACCESS_DENIED")


@pytest.mark.asyncio
async def test_invalid_transition_uses_the_error_envelope():
    from amp_server.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post(
            "/amp/v1/memories", headers=_HEADERS, json=_minimal_body()
        )
        assert created.status_code == 201
        resp = await client.delete(
            f"/amp/v1/memories/{created.json()['id']}", headers=_HEADERS
        )

    assert resp.status_code == 409
    _assert_error_envelope(resp.json(), "INVALID_TRANSITION")


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
