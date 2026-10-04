"""AMP Server — FastAPI application entry point."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse, Response

from amp_server.access_control import check_read_access, check_write_access
from amp_server.auth import ApiKeyStore, store_from_env
from amp_server.embeddings import provider_from_env
from amp_server.errors import (
    AMPError,
    access_denied,
    admin_disabled,
    invalid_transition,
    missing_agent_id,
    rate_limited,
    unauthenticated,
)
from amp_server.lifecycle import LifecycleEngine
from amp_server.limits import MAX_CELL_SIZE_BYTES
from amp_server.models import (
    ErrorResponse,
    LifecycleStatus,
    MemoryAccessPolicy,
    MemoryCell,
    MemoryCellCreate,
    MemoryCellUpdate,
    MemoryIdentity,
    MemoryLifecycle,
    MemoryProvenance,
    MemoryScoring,
    MemoryType,
    SearchRequest,
    SearchResponse,
)
from amp_server.paging import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, readable_page
from amp_server.ratelimit import (
    ScoringPatchLimiter,
    limit_from_env,
    patch_touches_scoring,
)
from amp_server.scheduler import lifecycle_loop, run_lifecycle, settings_from_env
from amp_server.storage.base import (
    InvalidTransitionError,
    MemoryNotFoundError,
    StorageAdapter,
)
from amp_server.storage.chroma import ChromaAdapter

logger = logging.getLogger(__name__)

AMP_VERSION = "0.1.0"


def configure_logging() -> None:
    """Make `amp_server.*` logs visible under any ASGI server.

    Uvicorn configures only its own `uvicorn.*` loggers and never the root
    logger, so module loggers like this one go nowhere by default — the server
    would start, schedule decay, and log none of it. `basicConfig` is a no-op
    when the embedder has already configured logging, so this defers to it.
    """
    logging.basicConfig(
        level=os.environ.get("AMP_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


_storage: StorageAdapter | None = None
_lifecycle: LifecycleEngine | None = None
_lifecycle_settings = settings_from_env()
# None means this deployment runs without API keys, and the identity header is
# trusted as the spec's binding describes. Set from the lifespan, so a key store
# that cannot be read stops the server rather than turning into a 401 later.
_api_key_store: ApiKeyStore | None = None
# Resolved here, like the lifecycle settings, so a test can swap either without
# reaching into the environment. The limiter is the stateful half.
_scoring_limit = limit_from_env()
_scoring_limiter = ScoringPatchLimiter(_scoring_limit)


def _build_storage() -> StorageAdapter:
    """Build the configured storage backend.

    Selected with `AMP_STORAGE_BACKEND` (`chroma` by default). An unknown name, or
    a backend whose configuration is missing, stops the server from starting:
    running against a different store than the operator asked for is a data
    problem, not a startup warning.
    """
    backend = os.environ.get("AMP_STORAGE_BACKEND", "chroma").strip().lower()
    provider = provider_from_env()

    if backend in ("", "chroma"):
        return ChromaAdapter(
            persist_directory=os.environ.get("AMP_PERSIST_DIR"),
            embedding_provider=provider,
        )

    if backend == "postgres":
        # Imported here so the optional driver is not needed to run chroma.
        from amp_server.storage.postgres import PostgresAdapter

        dsn = os.environ.get("AMP_POSTGRES_DSN")
        if not dsn:
            raise ValueError(
                "AMP_POSTGRES_DSN is required when AMP_STORAGE_BACKEND=postgres"
            )
        return PostgresAdapter(dsn=dsn, embedding_provider=provider)

    raise ValueError(
        f"unknown AMP_STORAGE_BACKEND {backend!r}; expected one of chroma, postgres"
    )


def get_storage() -> StorageAdapter:
    assert _storage is not None, "Storage not initialized — lifespan not started"
    return _storage


def get_api_key_store() -> ApiKeyStore | None:
    """The configured key store, or None when this deployment has no keys."""
    return _api_key_store


async def verified_agent_id(
    x_amp_agent_id: str | None = Header(default=None),
    x_amp_api_key: str | None = Header(default=None),
) -> str | None:
    """The caller's agent id, proven against the key store when one is configured.

    The single gate for every route that acts as an agent: identity resolution
    and its proof live here rather than in six handlers, so a new route cannot
    get one without the other. Returns None when no header was sent - the create
    route falls back to the body's `created_by`, and every other route raises
    `MISSING_AGENT_ID` itself.
    """
    store = get_api_key_store()
    if x_amp_agent_id is None:
        # With keys configured, an unproven identity must not slip in through the
        # body either: `create_memory` falls back to `identity.created_by`, which
        # would let any caller create a cell as any agent.
        if store is not None:
            raise unauthenticated()
        return None
    if store is None:
        return x_amp_agent_id
    if x_amp_api_key is None or not store.verify(x_amp_agent_id, x_amp_api_key):
        raise unauthenticated()
    return x_amp_agent_id


def get_lifecycle() -> LifecycleEngine:
    assert _lifecycle is not None, (
        "LifecycleEngine not initialized — lifespan not started"
    )
    return _lifecycle


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _storage, _lifecycle, _lifecycle_settings, _api_key_store
    global _scoring_limit, _scoring_limiter
    configure_logging()
    # Built here, not at import: a misconfigured backend must stop the server
    # from starting rather than surface as poor search results later.
    _storage = _build_storage()
    _lifecycle = LifecycleEngine(_storage)
    # Same reason: a key store that cannot be read must stop the server, not
    # fall back to trusting an unverified header.
    _api_key_store = store_from_env()

    # Read again here for the same reason the lifecycle settings are: a test (or
    # an embedder) can set AMP_SCORING_PATCH_LIMIT before starting the app.
    _scoring_limit = limit_from_env()
    _scoring_limiter = ScoringPatchLimiter(_scoring_limit)
    if _scoring_limit.enabled:
        logger.info(
            "Scoring PATCH limit: %d per %ds per cell",
            _scoring_limit.max_patches,
            _scoring_limit.window_seconds,
        )

    # Read settings here, not only at import: a test (or an embedder) can set
    # AMP_LIFECYCLE_* before starting the app and expect it to take effect.
    _lifecycle_settings = settings_from_env()

    task: asyncio.Task[None] | None = None
    if _lifecycle_settings.enabled:
        task = asyncio.create_task(lifecycle_loop(_lifecycle, _lifecycle_settings))
        logger.info(
            "Lifecycle scheduler started (every %ds)",
            _lifecycle_settings.interval_seconds,
        )
    else:
        logger.info("Lifecycle scheduler disabled (AMP_LIFECYCLE_ENABLED=false)")

    logger.info("AMP Server started")
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if _storage is not None:
            _storage.close()
        logger.info("AMP Server shutting down")


# ---------------------------------------------------------------------------
# App & router
# ---------------------------------------------------------------------------

app = FastAPI(
    title="AMP Server",
    version=AMP_VERSION,
    description="Agent Memory Protocol reference server implementation",
    lifespan=lifespan,
)

router = APIRouter(prefix="/amp/v1")


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@app.exception_handler(AMPError)
async def _amp_error_handler(request: Request, exc: AMPError) -> JSONResponse:
    """The single place an AMPError becomes an HTTP response.

    Registered once so every endpoint answers with the same
    `{"error": {"code", "message", "details"}}` body instead of each route
    building its own, and so route handlers can stay annotated `-> dict`.
    """
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_response(),
        headers=exc.headers or None,
    )


# The error envelope is part of the protocol, so it belongs in the contract
# rather than being left out of it: without these, `openapi.json` would document
# only the success path and a generated client would have nothing to type its
# error handling against.
_MISSING_AGENT_ID: dict[int | str, dict[str, Any]] = {
    401: {
        "model": ErrorResponse,
        "description": "X-AMP-Agent-ID header is required",
    }
}
_UNAUTHENTICATED: dict[int | str, dict[str, Any]] = {
    401: {
        "model": ErrorResponse,
        "description": "X-AMP-API-Key is missing or not valid for this agent id "
        "(only when AMP_API_KEYS_FILE is configured)",
    }
}
_RATE_LIMITED: dict[int | str, dict[str, Any]] = {
    429: {
        "model": ErrorResponse,
        "description": "Too many scoring updates for this cell; see Retry-After "
        "and GET /spec's scoring_patch_limit",
    }
}
_ACCESS_DENIED: dict[int | str, dict[str, Any]] = {
    403: {
        "model": ErrorResponse,
        "description": "Access denied; also returned when the cell does not exist",
    }
}
_INVALID_TRANSITION: dict[int | str, dict[str, Any]] = {
    409: {
        "model": ErrorResponse,
        "description": "The lifecycle transition is not permitted by the spec",
    }
}
_CELL_TOO_LARGE: dict[int | str, dict[str, Any]] = {
    413: {
        "model": ErrorResponse,
        "description": "The cell exceeds the maximum size advertised at GET /spec",
    }
}


# ---------------------------------------------------------------------------
# Health & spec
# ---------------------------------------------------------------------------


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "amp_version": AMP_VERSION}


@router.get("/spec")
async def spec() -> dict[str, Any]:
    return {
        "amp_version": AMP_VERSION,
        "capabilities": {
            "mcp_compatible": False,
            "storage_backends": [get_storage().name],
            # Open endpoint on purpose: a client can find out it needs a key
            # before it makes a call that would fail with 401.
            "api_keys_required": _api_key_store is not None,
            "max_page_size": MAX_PAGE_SIZE,
            "scoring_patch_limit": _scoring_limit.to_json(),
            "embedding": get_storage().embedding,
            "max_cell_size_bytes": MAX_CELL_SIZE_BYTES,
            "retention_days": get_storage().retention_days,
            "lifecycle_scheduler": {
                "enabled": _lifecycle_settings.enabled,
                "interval_seconds": _lifecycle_settings.interval_seconds,
                "manual_run_endpoint": "/amp/v1/lifecycle/run",
            },
        },
    }


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@router.post("/lifecycle/run", responses=_ACCESS_DENIED)
async def run_lifecycle_now(
    x_amp_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    """Trigger one lifecycle pass immediately — for cron, ops, or tests.

    Runs decay, plus the retention purge when `AMP_PURGE_RETENTION` is on. Gated
    on `AMP_ADMIN_TOKEN` because it mutates lifecycle state for every cell in
    storage, and erases data outright when purging is enabled. Unset token ==
    disabled (403), not an open endpoint.
    """
    configured = _lifecycle_settings.admin_token
    if not configured:
        raise admin_disabled()
    if x_amp_admin_token != configured:
        raise access_denied()

    run = await run_lifecycle(get_lifecycle(), _lifecycle_settings)
    return {"transitions": run.transitions, "purged": run.purged}


# ---------------------------------------------------------------------------
# Memory CRUD
# ---------------------------------------------------------------------------


@router.post(
    "/memories",
    status_code=201,
    responses=_UNAUTHENTICATED | _MISSING_AGENT_ID | _CELL_TOO_LARGE,
)
async def create_memory(
    body: MemoryCellCreate,
    x_amp_agent_id: str | None = Depends(verified_agent_id),
) -> dict[str, Any]:
    # Determine effective agent_id: header takes priority, fallback to created_by
    agent_id = x_amp_agent_id or body.identity.created_by
    if not agent_id:
        raise missing_agent_id()

    storage = get_storage()
    now = datetime.now(UTC)

    cell = MemoryCell(
        # id is auto-generated by the model with mem_ prefix
        type=body.type,
        content=body.content,
        identity=MemoryIdentity(
            owner_id=body.identity.owner_id,
            owner_type=body.identity.owner_type,
            created_by=agent_id,
            session_id=body.identity.session_id,
        ),
        lifecycle=MemoryLifecycle(
            created_at=now,
            status=LifecycleStatus.ACTIVE,
        ),
        scoring=body.scoring or MemoryScoring(),
        access_policy=body.access_policy or MemoryAccessPolicy(),
        provenance=body.provenance or MemoryProvenance(),
    )
    await storage.save(cell)
    return cell.model_dump(mode="json")


# Declared before `/memories/{memory_id}`: FastAPI matches routes in
# registration order, so a parameterised path declared first swallows the
# static ones - `/memories/query` was being read as a memory id named
# "query" and answered 403, making the documented alias unreachable.
@router.get("/memories", responses=_UNAUTHENTICATED | _MISSING_AGENT_ID)
@router.get("/memories/query", responses=_UNAUTHENTICATED | _MISSING_AGENT_ID)
async def query_memories(
    owner_id: str | None = None,
    type: MemoryType | None = None,
    status: LifecycleStatus | None = None,
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    x_amp_agent_id: str | None = Depends(verified_agent_id),
) -> dict[str, Any]:
    """List memory cells, one page at a time.

    `limit` counts cells this caller may read, and `offset` indexes that same
    readable stream; `has_more` says whether the next page holds anything. The
    response used to report `total`, which was the size of the page it had just
    returned - a number that read like a count of matches and was not one. A real
    count is not available without scanning the store on every call, so the field
    is gone rather than kept and distrusted.
    """
    if not x_amp_agent_id:
        raise missing_agent_id()

    page, has_more = await readable_page(
        get_storage(),
        agent_id=x_amp_agent_id,
        owner_id=owner_id,
        types=[type] if type else None,
        status=[status] if status else [LifecycleStatus.ACTIVE],
        limit=limit,
        offset=offset,
    )
    return {
        "results": [c.model_dump(mode="json") for c in page],
        "returned": len(page),
        "has_more": has_more,
        "offset": offset,
        "limit": limit,
    }


@router.get(
    "/memories/{memory_id}",
    responses=(_UNAUTHENTICATED | _MISSING_AGENT_ID | _ACCESS_DENIED),
)
async def get_memory(
    memory_id: str,
    x_amp_agent_id: str | None = Depends(verified_agent_id),
) -> dict[str, Any]:
    if not x_amp_agent_id:
        raise missing_agent_id()

    storage = get_storage()

    try:
        cell = await storage._get_raw(memory_id)
    except MemoryNotFoundError:
        # Per spec §8.4: return 403 regardless of existence to prevent oracle attack
        raise access_denied() from None

    if cell.lifecycle.status == LifecycleStatus.DELETED:
        raise access_denied()

    if not check_read_access(cell, x_amp_agent_id):
        raise access_denied()

    # Apply access boost (increments access_count, updates last_accessed_at)
    cell = await storage.get(memory_id)
    return cell.model_dump(mode="json")


@router.patch(
    "/memories/{memory_id}",
    responses=(
        _UNAUTHENTICATED
        | _MISSING_AGENT_ID
        | _ACCESS_DENIED
        | _INVALID_TRANSITION
        | _CELL_TOO_LARGE
        | _RATE_LIMITED
    ),
)
async def update_memory(
    memory_id: str,
    body: MemoryCellUpdate,
    x_amp_agent_id: str | None = Depends(verified_agent_id),
) -> dict[str, Any]:
    if not x_amp_agent_id:
        raise missing_agent_id()

    storage = get_storage()

    try:
        cell = await storage._get_raw(memory_id)
    except MemoryNotFoundError:
        raise access_denied() from None

    if cell.lifecycle.status == LifecycleStatus.DELETED:
        raise access_denied()

    if not check_write_access(cell, x_amp_agent_id):
        raise access_denied()

    if patch_touches_scoring(body):
        # RFC §5: a caller looping on `scoring` can hold a cell active past its
        # window or force a competitor into archive. Checked after the access
        # rules, so a caller who may not write this cell is told that, and told
        # nothing about how much budget is left. An allowed edit is recorded
        # here, before the write, so a write that then fails does not buy the
        # caller a free retry.
        wait = _scoring_limiter.check_and_record(memory_id)
        if wait:
            raise rate_limited(wait)

    try:
        updated = await storage.update(memory_id, body)
    except InvalidTransitionError as exc:
        raise invalid_transition(exc.message) from exc
    return updated.model_dump(mode="json")


@router.delete(
    "/memories/{memory_id}",
    status_code=204,
    responses=_UNAUTHENTICATED
    | _MISSING_AGENT_ID
    | _ACCESS_DENIED
    | _INVALID_TRANSITION,
)
async def delete_memory(
    memory_id: str,
    x_amp_agent_id: str | None = Depends(verified_agent_id),
) -> Response:
    if not x_amp_agent_id:
        raise missing_agent_id()

    storage = get_storage()

    try:
        cell = await storage._get_raw(memory_id)
    except MemoryNotFoundError:
        # Per spec §8.4: return ACCESS_DENIED (not 404) to prevent oracle attack
        raise access_denied() from None

    if cell.lifecycle.status == LifecycleStatus.DELETED:
        raise access_denied()

    if not check_write_access(cell, x_amp_agent_id):
        raise access_denied()

    try:
        await storage.mark_deleted(memory_id)
    except InvalidTransitionError as exc:
        raise invalid_transition(exc.message) from exc

    # The cell is gone from the API's point of view; its scoring budget has
    # nothing left to protect, and holding the counters would keep an id alive
    # in memory for a cell no caller can reach.
    _scoring_limiter.forget(memory_id)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


@router.post("/memories/search", responses=_UNAUTHENTICATED | _MISSING_AGENT_ID)
async def search_memories(
    body: SearchRequest,
    x_amp_agent_id: str | None = Depends(verified_agent_id),
) -> dict[str, Any]:
    if not x_amp_agent_id:
        raise missing_agent_id()

    storage = get_storage()
    results = await storage.search(body, agent_id=x_amp_agent_id)
    response = SearchResponse(results=results, returned=len(results), query=body.query)
    return response.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Register router
# ---------------------------------------------------------------------------

app.include_router(router)


def main() -> None:
    """Console-script entry point: run the server with uvicorn."""
    import uvicorn

    uvicorn.run(
        "amp_server.main:app",
        host=os.environ.get("AMP_HOST", "127.0.0.1"),
        port=int(os.environ.get("AMP_PORT", "8765")),
    )


if __name__ == "__main__":
    main()
