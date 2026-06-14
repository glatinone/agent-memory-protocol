from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from ulid import ULID


# --- Enums ---


class MemoryType(str, Enum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


class OwnerType(str, Enum):
    USER = "user"
    AGENT = "agent"
    ORGANIZATION = "organization"


class LifecycleStatus(str, Enum):
    ACTIVE = "active"
    STALE = "stale"
    ARCHIVED = "archived"
    DELETED = "deleted"


class SourceType(str, Enum):
    CONVERSATION = "conversation"
    DOCUMENT = "document"
    INFERENCE = "inference"
    USER_EXPLICIT = "user_explicit"


class ExtractionMethod(str, Enum):
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
                "id": "01J5A3B7K9M2N4P6Q8R0S1T3V5",
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
    lifecycle: MemoryLifecycle | None = None


# --- Search Models ---


class SearchRequest(BaseModel):
    query: str
    owner_id: str | None = None
    types: list[MemoryType] | None = None
    status: list[LifecycleStatus] = Field(
        default_factory=lambda: [LifecycleStatus.ACTIVE]
    )
    limit: int = Field(default=10, ge=1, le=100)
    include_stale: bool = False


class SearchResponse(BaseModel):
    results: list[MemoryCell]
    total: int
    query: str


# --- Error Models ---


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorDetail
