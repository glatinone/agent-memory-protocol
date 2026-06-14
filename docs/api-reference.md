# AMP API Reference

**Base URL:** `http://localhost:8765/amp/v1`  
**Protocol version:** `0.1.0`  
**Content-Type:** `application/json`

All endpoints accept and return JSON. Authentication is not enforced in the reference implementation but access control is expressed via `access_policy` on each memory cell.

---

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Server health check |
| GET | `/spec` | Protocol version and spec URL |
| POST | `/memories` | Create a memory cell |
| GET | `/memories/{memory_id}` | Retrieve a memory cell by ID |
| PATCH | `/memories/{memory_id}` | Update fields on a memory cell |
| DELETE | `/memories/{memory_id}` | Soft-delete a memory cell |
| POST | `/memories/search` | Semantic search over memory cells |

---

## GET /health

Returns server liveness status.

**Request**

```bash
curl http://localhost:8765/amp/v1/health
```

**Response `200 OK`**

```json
{
  "status": "ok",
  "amp_version": "0.1.0"
}
```

---

## GET /spec

Returns the protocol version and a link to the canonical spec.

**Request**

```bash
curl http://localhost:8765/amp/v1/spec
```

**Response `200 OK`**

```json
{
  "amp_version": "0.1.0",
  "spec_url": "https://github.com/AMP-Protocol/amp/blob/main/SPEC.md"
}
```

---

## POST /memories

Creates a new memory cell. The server assigns a ULID as the cell `id` and sets `lifecycle.created_at` automatically.

**Request**

```bash
curl -X POST http://localhost:8765/amp/v1/memories \
  -H "Content-Type: application/json" \
  -d '{
    "type": "semantic",
    "content": {
      "text": "User prefers Python for backend development",
      "metadata": {
        "domain": "programming",
        "language": "python"
      }
    },
    "identity": {
      "owner_id": "user-123",
      "owner_type": "user",
      "created_by": "agent-456",
      "session_id": "session-789"
    },
    "scoring": {
      "importance": 0.8,
      "confidence": 0.95,
      "decay_rate": 0.01
    },
    "access_policy": {
      "readable_by": ["agent-456"],
      "writable_by": ["agent-456"],
      "public": false
    },
    "provenance": {
      "source_type": "conversation",
      "source_ref": "conv-abc-123",
      "extraction_method": "llm_extraction"
    }
  }'
```

**Request body fields**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | `"episodic" \| "semantic" \| "procedural"` | Yes | Memory type |
| `content.text` | string | Yes | The memory content |
| `content.metadata` | object | No | Arbitrary key-value metadata |
| `identity.owner_id` | string | Yes | ID of the entity that owns this memory |
| `identity.owner_type` | `"user" \| "agent" \| "organization"` | Yes | Type of the owner |
| `identity.created_by` | string | Yes | ID of the agent or system that created this memory |
| `identity.session_id` | string | No | Session context in which memory was created |
| `scoring.importance` | float [0–1] | No | How important this memory is (default: `0.5`) |
| `scoring.confidence` | float [0–1] | No | Confidence in the memory's accuracy (default: `1.0`) |
| `scoring.decay_rate` | float ≥ 0 | No | Daily decay rate for the lifecycle engine (default: `0.01`) |
| `access_policy.readable_by` | string[] | No | IDs allowed to read this cell |
| `access_policy.writable_by` | string[] | No | IDs allowed to modify this cell |
| `access_policy.public` | bool | No | If `true`, any agent can read (default: `false`) |
| `provenance.source_type` | `"conversation" \| "document" \| "inference" \| "user_explicit"` | No | Origin of the memory |
| `provenance.source_ref` | string | No | Reference to the source (e.g. conversation ID) |
| `provenance.extraction_method` | `"llm_extraction" \| "rule_based" \| "user_explicit"` | No | How the memory was extracted |

**Response `201 Created`**

```json
{
  "amp_version": "0.1.0",
  "id": "01J5A3B7K9M2N4P6Q8R0S1T3V5",
  "type": "semantic",
  "content": {
    "text": "User prefers Python for backend development",
    "metadata": {
      "domain": "programming",
      "language": "python"
    }
  },
  "identity": {
    "owner_id": "user-123",
    "owner_type": "user",
    "created_by": "agent-456",
    "session_id": "session-789"
  },
  "lifecycle": {
    "created_at": "2026-06-12T10:00:00Z",
    "last_accessed_at": null,
    "last_updated_at": null,
    "expires_at": null,
    "status": "active"
  },
  "scoring": {
    "importance": 0.8,
    "confidence": 0.95,
    "decay_rate": 0.01,
    "access_count": 0
  },
  "access_policy": {
    "readable_by": ["agent-456"],
    "writable_by": ["agent-456"],
    "public": false
  },
  "provenance": {
    "source_type": "conversation",
    "source_ref": "conv-abc-123",
    "extraction_method": "llm_extraction"
  }
}
```

**Error responses**

| Status | `error.code` | Cause |
|--------|-------------|-------|
| `422` | `VALIDATION_ERROR` | Missing required fields or invalid enum value |

---

## GET /memories/{memory_id}

Retrieves a single memory cell by its ULID. Also increments `scoring.access_count` and updates `lifecycle.last_accessed_at`.

**Request**

```bash
curl http://localhost:8765/amp/v1/memories/01J5A3B7K9M2N4P6Q8R0S1T3V5
```

**Path parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `memory_id` | string (ULID) | The ID returned when the cell was created |

**Response `200 OK`**

```json
{
  "amp_version": "0.1.0",
  "id": "01J5A3B7K9M2N4P6Q8R0S1T3V5",
  "type": "semantic",
  "content": {
    "text": "User prefers Python for backend development",
    "metadata": {
      "domain": "programming",
      "language": "python"
    }
  },
  "identity": {
    "owner_id": "user-123",
    "owner_type": "user",
    "created_by": "agent-456",
    "session_id": "session-789"
  },
  "lifecycle": {
    "created_at": "2026-06-12T10:00:00Z",
    "last_accessed_at": "2026-06-12T10:05:00Z",
    "last_updated_at": null,
    "expires_at": null,
    "status": "active"
  },
  "scoring": {
    "importance": 0.8,
    "confidence": 0.95,
    "decay_rate": 0.01,
    "access_count": 1
  },
  "access_policy": {
    "readable_by": ["agent-456"],
    "writable_by": ["agent-456"],
    "public": false
  },
  "provenance": {
    "source_type": "conversation",
    "source_ref": "conv-abc-123",
    "extraction_method": "llm_extraction"
  }
}
```

**Error responses**

| Status | `error.code` | Cause |
|--------|-------------|-------|
| `404` | `NOT_FOUND` | No cell with the given ID |
| `403` | `FORBIDDEN` | Caller is not in `readable_by` and `public` is `false` |

---

## PATCH /memories/{memory_id}

Partially updates a memory cell. Only the fields you send are changed; all others are preserved. Updates `lifecycle.last_updated_at` automatically.

**Request**

```bash
curl -X PATCH http://localhost:8765/amp/v1/memories/01J5A3B7K9M2N4P6Q8R0S1T3V5 \
  -H "Content-Type: application/json" \
  -d '{
    "content": {
      "text": "User strongly prefers Python for backend; also comfortable with Go",
      "metadata": {
        "domain": "programming",
        "language": "python",
        "secondary_language": "go"
      }
    },
    "scoring": {
      "importance": 0.9
    }
  }'
```

**Request body**

Any subset of the writable fields from the `MemoryCell` schema. Nested objects are merged at the top level of each sub-object (e.g., sending `scoring.importance` does not clear `scoring.confidence`).

| Field | Notes |
|-------|-------|
| `content` | Replace content text and/or metadata |
| `scoring` | Adjust importance, confidence, or decay_rate |
| `access_policy` | Update read/write ACLs |
| `lifecycle.status` | Manually transition status (e.g., force to `"archived"`) |
| `lifecycle.expires_at` | Set or clear expiry timestamp |

Fields that cannot be patched: `id`, `amp_version`, `identity`, `lifecycle.created_at`.

**Response `200 OK`** — the full updated cell

```json
{
  "amp_version": "0.1.0",
  "id": "01J5A3B7K9M2N4P6Q8R0S1T3V5",
  "type": "semantic",
  "content": {
    "text": "User strongly prefers Python for backend; also comfortable with Go",
    "metadata": {
      "domain": "programming",
      "language": "python",
      "secondary_language": "go"
    }
  },
  "identity": {
    "owner_id": "user-123",
    "owner_type": "user",
    "created_by": "agent-456",
    "session_id": "session-789"
  },
  "lifecycle": {
    "created_at": "2026-06-12T10:00:00Z",
    "last_accessed_at": "2026-06-12T10:05:00Z",
    "last_updated_at": "2026-06-12T10:10:00Z",
    "expires_at": null,
    "status": "active"
  },
  "scoring": {
    "importance": 0.9,
    "confidence": 0.95,
    "decay_rate": 0.01,
    "access_count": 1
  },
  "access_policy": {
    "readable_by": ["agent-456"],
    "writable_by": ["agent-456"],
    "public": false
  },
  "provenance": {
    "source_type": "conversation",
    "source_ref": "conv-abc-123",
    "extraction_method": "llm_extraction"
  }
}
```

**Error responses**

| Status | `error.code` | Cause |
|--------|-------------|-------|
| `404` | `NOT_FOUND` | No cell with the given ID |
| `403` | `FORBIDDEN` | Caller is not in `writable_by` |
| `422` | `VALIDATION_ERROR` | Invalid field value |

---

## DELETE /memories/{memory_id}

Soft-deletes a memory cell by setting `lifecycle.status` to `"deleted"`. The cell is retained in storage and will not appear in search results, but can still be retrieved directly by ID.

**Request**

```bash
curl -X DELETE http://localhost:8765/amp/v1/memories/01J5A3B7K9M2N4P6Q8R0S1T3V5
```

**Path parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `memory_id` | string (ULID) | The ID of the cell to delete |

**Response `204 No Content`**

Empty body.

**Error responses**

| Status | `error.code` | Cause |
|--------|-------------|-------|
| `404` | `NOT_FOUND` | No cell with the given ID |
| `403` | `FORBIDDEN` | Caller is not in `writable_by` |

---

## POST /memories/search

Performs semantic (vector) search over active memory cells for a given owner. Results are ranked by relevance to the query.

**Request**

```bash
curl -X POST http://localhost:8765/amp/v1/memories/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "what programming languages does the user know?",
    "owner_id": "user-123",
    "types": ["semantic", "episodic"],
    "status": ["active"],
    "limit": 5,
    "include_stale": false
  }'
```

**Request body fields**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | string | Yes | Natural language query to search against memory content |
| `owner_id` | string | Yes | Only return cells belonging to this owner |
| `types` | string[] | No | Filter to specific memory types. Omit to search all types |
| `status` | string[] | No | Lifecycle statuses to include (default: `["active"]`) |
| `limit` | int [1–100] | No | Maximum number of results to return (default: `10`) |
| `include_stale` | bool | No | Shorthand to add `"stale"` to the status filter (default: `false`) |

**Response `200 OK`**

```json
{
  "results": [
    {
      "amp_version": "0.1.0",
      "id": "01J5A3B7K9M2N4P6Q8R0S1T3V5",
      "type": "semantic",
      "content": {
        "text": "User prefers Python for backend development",
        "metadata": {
          "domain": "programming",
          "language": "python"
        }
      },
      "identity": {
        "owner_id": "user-123",
        "owner_type": "user",
        "created_by": "agent-456",
        "session_id": "session-789"
      },
      "lifecycle": {
        "created_at": "2026-06-12T10:00:00Z",
        "last_accessed_at": "2026-06-12T10:05:00Z",
        "last_updated_at": null,
        "expires_at": null,
        "status": "active"
      },
      "scoring": {
        "importance": 0.8,
        "confidence": 0.95,
        "decay_rate": 0.01,
        "access_count": 1
      },
      "access_policy": {
        "readable_by": ["agent-456"],
        "writable_by": ["agent-456"],
        "public": false
      },
      "provenance": {
        "source_type": "conversation",
        "source_ref": "conv-abc-123",
        "extraction_method": "llm_extraction"
      }
    }
  ],
  "total": 1,
  "query": "what programming languages does the user know?"
}
```

**Response fields**

| Field | Description |
|-------|-------------|
| `results` | Array of matching `MemoryCell` objects, ordered by relevance |
| `total` | Total number of cells matched (may exceed `limit`) |
| `query` | The query string echoed back |

**Error responses**

| Status | `error.code` | Cause |
|--------|-------------|-------|
| `422` | `VALIDATION_ERROR` | Missing `query` or `owner_id`, or `limit` out of range |

---

## Data types

### MemoryType

| Value | Description |
|-------|-------------|
| `episodic` | Specific past events or interactions |
| `semantic` | Facts, preferences, and general knowledge |
| `procedural` | How-to knowledge and learned behaviors |

### OwnerType

| Value | Description |
|-------|-------------|
| `user` | A human user |
| `agent` | An AI agent or system |
| `organization` | A shared organizational context |

### LifecycleStatus

| Value | Description |
|-------|-------------|
| `active` | Normal operational state |
| `stale` | Decay score dropped below `0.3`; not deleted but deprioritized |
| `archived` | Stale for ≥ 30 days; moved to cold storage |
| `deleted` | Soft-deleted; excluded from search |

### Decay score formula

The lifecycle engine computes a decay score on each cell to drive automatic `active → stale → archived` transitions:

```
score = importance × confidence × e^(−decay_rate × Δt_days)
```

A cell transitions to `stale` when its score falls below `0.3`. A `stale` cell transitions to `archived` after 30 days without an update.

---

## Error response shape

All error responses use the following structure:

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Memory cell 01J5A3B7K9M2N4P6Q8R0S1T3V5 not found",
    "details": {}
  }
}
```

| Field | Description |
|-------|-------------|
| `error.code` | Machine-readable error code in `SCREAMING_SNAKE_CASE` |
| `error.message` | Human-readable description |
| `error.details` | Optional structured context (field errors, etc.) |
