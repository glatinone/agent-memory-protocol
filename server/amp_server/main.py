"""AMP Server — FastAPI application entry point."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, FastAPI, Header
from fastapi.responses import JSONResponse, Response

from amp_server.access_control import check_read_access, check_write_access
from amp_server.lifecycle import LifecycleEngine
from amp_server.scheduler import lifecycle_loop, run_lifecycle, settings_from_env
from amp_server.models import (
    ErrorDetail,
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
    SearchRequest,
    SearchResponse,
    MemoryType,
)
from amp_server.storage.base import InvalidTransitionError, MemoryNotFoundError
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

_storage: ChromaAdapter | None = None
_lifecycle: LifecycleEngine | None = None
_lifecycle_settings = settings_from_env()


def get_storage() -> ChromaAdapter:
    assert _storage is not None, "Storage not initialized — lifespan not started"
    return _storage


def get_lifecycle() -> LifecycleEngine:
    assert _lifecycle is not None, "LifecycleEngine not initialized — lifespan not started"
    return _lifecycle


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _storage, _lifecycle, _lifecycle_settings
    configure_logging()
    persist_dir = os.environ.get("AMP_PERSIST_DIR")
    _storage = ChromaAdapter(persist_directory=persist_dir)
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
        logger.info("AMP Server shutting down")


# ---------------------------------------------------------------------------
# App & router
# ---------------------------------------------------------------------------

app = FastAPI(
    title="AMP Server",
    version=AMP_VERSION,
    description="Agent Memory Protocol — Reference Server Implementation",
    lifespan=lifespan,
)

router = APIRouter(prefix="/amp/v1")


# ---------------------------------------------------------------------------
# Error helpers
# ---------------------------------------------------------------------------


def _err(code: str, message: str, details: dict | None = None) -> dict[str, Any]:
    return ErrorResponse(
        error=ErrorDetail(code=code, message=message, details=details or {})
    ).model_dump()


def _missing_agent_id() -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content=_err("MISSING_AGENT_ID", "X-AMP-Agent-ID header is required"),
    )


def _access_denied() -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content=_err("ACCESS_DENIED", "Access denied"),
    )


def _admin_disabled() -> JSONResponse:
    """Manual lifecycle runs are opt-in: no token configured means no access."""
    return JSONResponse(
        status_code=403,
        content=_err(
            "ADMIN_DISABLED",
            "Manual lifecycle runs are disabled; set AMP_ADMIN_TOKEN to enable",
        ),
    )


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
            "storage_backends": ["chroma"],
            "max_cell_size_bytes": 65536,
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


@router.post("/lifecycle/run")
async def run_lifecycle_now(
    x_amp_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    """Trigger one decay pass immediately — for cron, ops, or tests.

    Gated on `AMP_ADMIN_TOKEN` because it mutates lifecycle state for every
    cell in storage. Unset token == disabled (403), not an open endpoint.
    """
    configured = _lifecycle_settings.admin_token
    if not configured:
        return _admin_disabled()
    if x_amp_admin_token != configured:
        return _access_denied()

    transitions = await run_lifecycle(get_lifecycle())
    return {"transitions": transitions}


# ---------------------------------------------------------------------------
# Memory CRUD
# ---------------------------------------------------------------------------


@router.post("/memories", status_code=201)
async def create_memory(
    body: MemoryCellCreate,
    x_amp_agent_id: str | None = Header(default=None),
) -> dict[str, Any]:
    # Determine effective agent_id: header takes priority, fallback to created_by
    agent_id = x_amp_agent_id or body.identity.created_by
    if not agent_id:
        return _missing_agent_id()

    storage = get_storage()
    now = datetime.now(timezone.utc)

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


@router.get("/memories/{memory_id}")
async def get_memory(
    memory_id: str,
    x_amp_agent_id: str | None = Header(default=None),
) -> dict[str, Any]:
    if not x_amp_agent_id:
        return _missing_agent_id()

    storage = get_storage()

    try:
        cell = await storage._get_raw(memory_id)
    except MemoryNotFoundError:
        # Per spec §8.4: return 403 regardless of existence to prevent oracle attack
        return _access_denied()

    if cell.lifecycle.status == LifecycleStatus.DELETED:
        return _access_denied()

    if not check_read_access(cell, x_amp_agent_id):
        return _access_denied()

    # Apply access boost (increments access_count, updates last_accessed_at)
    cell = await storage.get(memory_id)
    return cell.model_dump(mode="json")


@router.patch("/memories/{memory_id}")
async def update_memory(
    memory_id: str,
    body: MemoryCellUpdate,
    x_amp_agent_id: str | None = Header(default=None),
) -> dict[str, Any]:
    if not x_amp_agent_id:
        return _missing_agent_id()

    storage = get_storage()

    try:
        cell = await storage._get_raw(memory_id)
    except MemoryNotFoundError:
        return _access_denied()

    if cell.lifecycle.status == LifecycleStatus.DELETED:
        return _access_denied()

    if not check_write_access(cell, x_amp_agent_id):
        return _access_denied()

    try:
        updated = await storage.update(memory_id, body)
    except InvalidTransitionError as exc:
        return JSONResponse(status_code=409, content={"detail": str(exc)})
    return updated.model_dump(mode="json")


@router.delete("/memories/{memory_id}")
async def delete_memory(
    memory_id: str,
    x_amp_agent_id: str | None = Header(default=None),
) -> Response:
    if not x_amp_agent_id:
        return _missing_agent_id()

    storage = get_storage()

    try:
        cell = await storage._get_raw(memory_id)
    except MemoryNotFoundError:
        # Per spec §8.4: return ACCESS_DENIED (not 404) to prevent oracle attack
        return _access_denied()

    if cell.lifecycle.status == LifecycleStatus.DELETED:
        return _access_denied()

    if not check_write_access(cell, x_amp_agent_id):
        return _access_denied()

    try:
        await storage.mark_deleted(memory_id)
    except InvalidTransitionError as exc:
        return JSONResponse(
            status_code=409,
            content=_err("INVALID_TRANSITION", exc.message),
        )

    return Response(status_code=204)


@router.get("/memories")
@router.get("/memories/query")
async def query_memories(
    owner_id: str | None = None,
    type: MemoryType | None = None,
    status: LifecycleStatus | None = None,
    limit: int = 20,
    x_amp_agent_id: str | None = Header(default=None),
) -> dict[str, Any]:
    if not x_amp_agent_id:
        return _missing_agent_id()

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


@router.post("/memories/search")
async def search_memories(
    body: SearchRequest,
    x_amp_agent_id: str | None = Header(default=None),
) -> dict[str, Any]:
    if not x_amp_agent_id:
        return _missing_agent_id()

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
