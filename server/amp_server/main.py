"""AMP Server — FastAPI application entry point."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, FastAPI, Header, Request
from fastapi.responses import JSONResponse, Response

from amp_server.access_control import check_read_access, check_write_access
from amp_server.embeddings import provider_from_env
from amp_server.errors import (
    AMPError,
    access_denied,
    admin_disabled,
    invalid_transition,
    missing_agent_id,
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
    global _storage, _lifecycle, _lifecycle_settings
    configure_logging()
    # Built here, not at import: a misconfigured backend must stop the server
    # from starting rather than surface as poor search results later.
    _storage = _build_storage()
    _lifecycle = LifecycleEngine(_storage)

    # Read settings here, not only at import: a test (or an embedder) can set
    # AMP_LIFECYCLE_* before starting the app and expect it to take effect.
    _lifecycle_settings = settings_from_env()

    task: asyncio.Task[None] | None = None
    if _lifecycle_settings.enabled:
        task = asyncio.create_task(
            lifecycle_loop(_lifecycle, _lifecycle_settings.interval_seconds)
        )
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
    return JSONResponse(status_code=exc.status_code, content=exc.to_response())


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
            "embedding": get_storage().embedding,
            "max_cell_size_bytes": MAX_CELL_SIZE_BYTES,
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
    """Trigger one decay pass immediately — for cron, ops, or tests.

    Gated on `AMP_ADMIN_TOKEN` because it mutates lifecycle state for every
    cell in storage. Unset token == disabled (403), not an open endpoint.
    """
    configured = _lifecycle_settings.admin_token
    if not configured:
        raise admin_disabled()
    if x_amp_admin_token != configured:
        raise access_denied()

    transitions = await run_lifecycle(get_lifecycle())
    return {"transitions": transitions}


# ---------------------------------------------------------------------------
# Memory CRUD
# ---------------------------------------------------------------------------


@router.post(
    "/memories",
    status_code=201,
    responses=_MISSING_AGENT_ID | _CELL_TOO_LARGE,
)
async def create_memory(
    body: MemoryCellCreate,
    x_amp_agent_id: str | None = Header(default=None),
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


@router.get("/memories/{memory_id}", responses=_MISSING_AGENT_ID | _ACCESS_DENIED)
async def get_memory(
    memory_id: str,
    x_amp_agent_id: str | None = Header(default=None),
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
        _MISSING_AGENT_ID | _ACCESS_DENIED | _INVALID_TRANSITION | _CELL_TOO_LARGE
    ),
)
async def update_memory(
    memory_id: str,
    body: MemoryCellUpdate,
    x_amp_agent_id: str | None = Header(default=None),
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

    try:
        updated = await storage.update(memory_id, body)
    except InvalidTransitionError as exc:
        raise invalid_transition(exc.message) from exc
    return updated.model_dump(mode="json")


@router.delete(
    "/memories/{memory_id}",
    status_code=204,
    responses=_MISSING_AGENT_ID | _ACCESS_DENIED | _INVALID_TRANSITION,
)
async def delete_memory(
    memory_id: str,
    x_amp_agent_id: str | None = Header(default=None),
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

    return Response(status_code=204)


@router.get("/memories", responses=_MISSING_AGENT_ID)
@router.get("/memories/query", responses=_MISSING_AGENT_ID)
async def query_memories(
    owner_id: str | None = None,
    type: MemoryType | None = None,
    status: LifecycleStatus | None = None,
    limit: int = 20,
    x_amp_agent_id: str | None = Header(default=None),
) -> dict[str, Any]:
    if not x_amp_agent_id:
        raise missing_agent_id()

    storage = get_storage()
    types_list = [type] if type else None
    status_list = [status] if status else [LifecycleStatus.ACTIVE]

    cells = await storage.query(
        owner_id=owner_id,
        types=types_list,
        status=status_list,
        limit=limit,
    )

    allowed_cells = [c for c in cells if check_read_access(c, x_amp_agent_id)]
    return {
        "results": [c.model_dump(mode="json") for c in allowed_cells],
        "total": len(allowed_cells),
    }


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


@router.post("/memories/search", responses=_MISSING_AGENT_ID)
async def search_memories(
    body: SearchRequest,
    x_amp_agent_id: str | None = Header(default=None),
) -> dict[str, Any]:
    if not x_amp_agent_id:
        raise missing_agent_id()

    storage = get_storage()
    results = await storage.search(body, agent_id=x_amp_agent_id)
    response = SearchResponse(results=results, total=len(results), query=body.query)
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
