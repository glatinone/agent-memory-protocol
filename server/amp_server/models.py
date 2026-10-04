from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from ulid import ULID

# --- Enums ---


class MemoryType(StrEnum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


class OwnerType(StrEnum):
    USER = "user"
    AGENT = "agent"
    ORGANIZATION = "organization"


class LifecycleStatus(StrEnum):
    ACTIVE = "active"
    STALE = "stale"
    ARCHIVED = "archived"
    DELETED = "deleted"


class SourceType(StrEnum):
    CONVERSATION = "conversation"
    DOCUMENT = "document"
    INFERENCE = "inference"
    USER_EXPLICIT = "user_explicit"


class ExtractionMethod(StrEnum):
    LLM_EXTRACTION = "llm_extraction"
    RULE_BASED = "rule_based"
    USER_EXPLICIT = "user_explicit"


# --- Component Models ---


class MemoryContent(BaseModel):
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryIdentity(BaseModel):
    owner_id: str
    owner_type: OwnerType
    created_by: str | None = None
    session_id: str | None = None


class MemoryLifecycle(BaseModel):
    created_at: datetime
    last_accessed_at: datetime | None = None
    last_updated_at: datetime | None = None
    expires_at: datetime | None = None
    status: LifecycleStatus = LifecycleStatus.ACTIVE


class MemoryLifecycleUpdate(BaseModel):
    """The part of `lifecycle` a client may change.

    `created_at` is absent rather than merely optional, and that difference is the
    point: the server sets it at create time and the decay formula measures from
    it, so a client able to rewrite it could reset a cell's apparent age and
    defeat the same decay the lifecycle engine applies. `docs/api-reference.md`
    already documented it as unpatchable; the schema now enforces that.

    An update is merged into the stored lifecycle, so a field the client does not
    send is a field that keeps its value. That is what makes
    `PATCH {"lifecycle": {"status": "archived"}}` enough to archive a cell - before
    this, `created_at` was required by the shared model, so every client had to
    GET the cell first and echo the timestamp back. The SDKs did exactly that.

    The other timestamps stay writable because echoing them is harmless: the
    server stamps `last_updated_at` on every write regardless.
    """

    last_accessed_at: datetime | None = None
    last_updated_at: datetime | None = None
    expires_at: datetime | None = None
    status: LifecycleStatus | None = None


class MemoryScoring(BaseModel):
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    decay_rate: float = Field(default=0.01, ge=0.0)
    access_count: int = Field(default=0, ge=0)


class MemoryAccessPolicy(BaseModel):
    readable_by: list[str] = Field(default_factory=list)
    writable_by: list[str] = Field(default_factory=list)
    public: bool = False


class MemoryProvenance(BaseModel):
    source_type: SourceType | None = None
    source_ref: str | None = None
    extraction_method: ExtractionMethod | None = None


# --- Primary Models ---


class MemoryCell(BaseModel):
    amp_version: str = "0.1.0"
    id: str = Field(default_factory=lambda: f"mem_{ULID()}")
    type: MemoryType
    content: MemoryContent
    identity: MemoryIdentity
    lifecycle: MemoryLifecycle
    scoring: MemoryScoring = Field(default_factory=MemoryScoring)
    access_policy: MemoryAccessPolicy = Field(default_factory=MemoryAccessPolicy)
    provenance: MemoryProvenance = Field(default_factory=MemoryProvenance)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "amp_version": "0.1.0",
                "id": "mem_01J5A3B7K9M2N4P6Q8R0S1T3V5",
                "type": "semantic",
                "content": {
                    "text": "User prefers Python for backend development",
                    "metadata": {"domain": "programming", "language": "python"},
                },
                "identity": {
                    "owner_id": "user-123",
                    "owner_type": "user",
                    "created_by": "agent-456",
                    "session_id": "session-789",
                },
                "lifecycle": {
                    "created_at": "2025-01-01T00:00:00Z",
                    "status": "active",
                },
                "scoring": {
                    "importance": 0.8,
                    "confidence": 0.95,
                    "decay_rate": 0.01,
                    "access_count": 5,
                },
                "access_policy": {
                    "readable_by": ["agent-456"],
                    "writable_by": ["agent-456"],
                    "public": False,
                },
                "provenance": {
                    "source_type": "conversation",
                    "source_ref": "conv-abc-123",
                    "extraction_method": "llm_extraction",
                },
            }
        }
    )


class MemoryCellCreate(BaseModel):
    type: MemoryType
    content: MemoryContent
    identity: MemoryIdentity
    scoring: MemoryScoring | None = None
    access_policy: MemoryAccessPolicy | None = None
    provenance: MemoryProvenance | None = None


class MemoryCellUpdate(BaseModel):
    """Partial update model. MUST NOT include id, type, amp_version, or identity."""

    content: MemoryContent | None = None
    scoring: MemoryScoring | None = None
    access_policy: MemoryAccessPolicy | None = None
    provenance: MemoryProvenance | None = None
    lifecycle: MemoryLifecycleUpdate | None = None


# --- Search Models ---


#: The largest page any endpoint returns. It lives beside the request models
#: because it is part of the request contract: the search model bounds `limit`
#: with it and the listing routes do too, so no endpoint can promise a client one
#: ceiling while the next refuses it. Two hard-coded 100s is how that drifts.
MAX_PAGE_SIZE = 100


class SearchRequest(BaseModel):
    query: str
    owner_id: str | None = None
    types: list[MemoryType] | None = None
    status: list[LifecycleStatus] = Field(
        default_factory=lambda: [LifecycleStatus.ACTIVE]
    )
    # Default 10 rather than the listing endpoints' 20: that is what search has
    # always used, and a default is not worth breaking clients over.
    limit: int = Field(default=10, ge=1, le=MAX_PAGE_SIZE)
    #: Skips this many results *the caller may read*, so page 2 is page 2 of the
    #: caller's own view, exactly as `offset` on the listing endpoints is.
    offset: int = Field(default=0, ge=0)
    include_stale: bool = False


class SearchResponse(BaseModel):
    """Search results for one page.

    The fields say what the page is and what it is not. `returned` is the size of
    this page - the field was called `total` and documented as "may exceed
    `limit`", which it never could, because the value was the length of the list
    beside it. `has_more` is the honest answer to "is there more", and `offset` /
    `limit` echo the window so a client can page without keeping its own count.
    """

    results: list[MemoryCell]
    returned: int
    has_more: bool
    offset: int
    limit: int
    query: str


# --- Error Models ---


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorDetail
