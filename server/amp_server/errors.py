"""Protocol errors and the single HTTP error shape AMP returns.

Every endpoint raises `AMPError` instead of building a `JSONResponse` inline.
`main.py` registers one handler for it, so the wire shape is identical
(`{"error": {"code", "message", "details"}}`) on every endpoint and status code,
and the route handlers stay annotated `-> dict`.

Before this, `PATCH /memories/{id}` answered 409 with `{"detail": ...}` while
`DELETE` answered 409 with `{"error": ...}`; both SDKs only understand the
latter, so a client hitting the PATCH conflict got a generic message.
"""

from __future__ import annotations

from typing import Any

from amp_server.models import ErrorDetail, ErrorResponse


class AMPError(Exception):
    """An error that maps onto a documented AMP error response."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}
        # Part of the error for a caller who can act on it: a rate limit that
        # does not say how long to wait leaves the client to guess.
        self.headers = headers or {}
        super().__init__(message)

    def to_response(self) -> dict[str, Any]:
        """Build the `{"error": {...}}` body as a plain dict."""
        return ErrorResponse(
            error=ErrorDetail(
                code=self.code, message=self.message, details=self.details
            )
        ).model_dump()


def missing_agent_id() -> AMPError:
    """Per spec §8.1: the agent identity header is required."""
    return AMPError(401, "MISSING_AGENT_ID", "X-AMP-Agent-ID header is required")


def access_denied() -> AMPError:
    """Used for both "not permitted" and "does not exist", per spec §8.4.

    Returning the same error for a missing cell and a forbidden one is
    deliberate: a different response for the two would let a caller probe for
    the existence of cells it cannot read.
    """
    return AMPError(403, "ACCESS_DENIED", "Access denied")


def unauthenticated() -> AMPError:
    """No key, or a key that does not belong to the claimed agent id.

    One response for both, so the endpoint cannot be used to find out which agent
    ids exist. Raised only when a key store is configured; without one the header
    is trusted, as the spec's binding describes.
    """
    return AMPError(
        401,
        "UNAUTHENTICATED",
        "X-AMP-API-Key is missing or not valid for this agent id",
    )


def validation_error(field_errors: list[dict[str, Any]]) -> AMPError:
    """A request body the schema rejects (spec §8.1).

    The per-field detail goes in `details.errors`, which is what `details` is for:
    a caller needs to know which field was wrong, and the protocol needs one error
    shape on every response.
    """
    return AMPError(
        422,
        "VALIDATION_ERROR",
        "Request validation failed",
        details={"errors": field_errors},
    )


def rate_limited(retry_after_seconds: int) -> AMPError:
    """Too many scoring edits on one cell (RFC §5: decay-score manipulation).

    `429` with `Retry-After`, because the caller can act on the number: it is
    exactly how long until the oldest allowed edit ages out of the window.
    """
    return AMPError(
        429,
        "RATE_LIMITED",
        f"too many scoring updates for this cell; retry in {retry_after_seconds}s",
        details={"retry_after_seconds": retry_after_seconds},
        headers={"Retry-After": str(retry_after_seconds)},
    )


def admin_disabled() -> AMPError:
    """Manual lifecycle runs are opt-in: no token configured means no access."""
    return AMPError(
        403,
        "ADMIN_DISABLED",
        "Manual lifecycle runs are disabled; set AMP_ADMIN_TOKEN to enable",
    )


def invalid_transition(message: str) -> AMPError:
    """A lifecycle transition the spec does not allow (spec §6.1)."""
    return AMPError(409, "INVALID_TRANSITION", message)
