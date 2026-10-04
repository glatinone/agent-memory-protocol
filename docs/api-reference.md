# AMP API Reference

**Base URL:** `http://localhost:8765/amp/v1`  
**Protocol version:** `0.1.0`  
**Content-Type:** `application/json`

All endpoints accept and return JSON. Memory-cell access control is expressed via `access_policy` on each cell; the only endpoint with its own auth is `POST /lifecycle/run`, gated on an admin token.

---

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Server health check |
| GET | `/spec` | Protocol version and this server's declared capabilities |
| POST | `/memories` | Create a memory cell |
| GET | `/memories/{memory_id}` | Retrieve a memory cell by ID |
| PATCH | `/memories/{memory_id}` | Update fields on a memory cell |
| DELETE | `/memories/{memory_id}` | Soft-delete a memory cell (the cell must be `archived` first) |
| GET | `/memories` | List memory cells by `owner_id` and `type` |
| GET | `/memories/query` | Alias of `GET /memories` |
| POST | `/memories/search` | Semantic search over memory cells |
| POST | `/lifecycle/run` | Run one decay pass now (admin token required) |

---

## Machine-readable contract

The table above is prose. The contract itself is
[`spec/v0.1.0/openapi.json`](https://github.com/glatinone/agent-memory-protocol/blob/master/spec/v0.1.0/openapi.json),
generated from the reference server and committed, and a running server serves the
same document at `/openapi.json` (with interactive docs at `/docs`).

It is committed rather than only served so that a change to the API surface shows
up as a reviewable diff, and two tests keep it honest: one on the server, one in
the SDK. Errors are part of the contract too - every route declares the `401`,
`403` and `409` responses it can return, using the same
`{"error": {"code", "message", "details"}}` envelope on all of them.

If you are implementing AMP elsewhere, the fastest way to know where you stand is
the [conformance suite](https://github.com/glatinone/agent-memory-protocol/blob/master/conformance/README.md):

```bash
amp-conformance --base-url https://your-server.example.com
```

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

Returns the protocol version and this server's declared capabilities.

**Request**

```bash
curl http://localhost:8765/amp/v1/spec
```

**Response `200 OK`**

```json
{
  "amp_version": "0.1.0",
  "capabilities": {
    "mcp_compatible": false,
    "storage_backends": ["chroma"],
    "embedding": {"provider": "chroma-default", "dimensions": 384},
    "max_cell_size_bytes": 65536,
    "retention_days": 30,
    "lifecycle_scheduler": {
      "enabled": true,
      "interval_seconds": 3600,
      "manual_run_endpoint": "/amp/v1/lifecycle/run"
    }
  }
}
```

For the canonical protocol spec itself (not this endpoint), see
[spec/v0.1.0/memory-cell.schema.json](https://github.com/glatinone/agent-memory-protocol/blob/master/spec/v0.1.0/memory-cell.schema.json) and
[spec/v0.1.0/lifecycle.md](https://github.com/glatinone/agent-memory-protocol/blob/master/spec/v0.1.0/lifecycle.md).

**Each capability is a claim the server has to honour**, and the conformance
suite checks it against the server's own numbers rather than a fixed value:

| Capability | What it commits the server to |
|---|---|
| `mcp_compatible` | Whether **this HTTP server** speaks MCP directly. It is `false`: the MCP integration ships as a separate stdio process (`amp-mcp`, see `examples/mcp-claude-desktop/`), not as an endpoint on this API. |
| `storage_backends` | The adapter actually wired in (`chroma` or `postgres`), selected with `AMP_STORAGE_BACKEND`; see [getting started](getting-started.md#6-choosing-a-storage-backend). |
| `embedding` | Which provider turns text into vectors, and the width of the vectors it produces (`null` when the service decides per request). Configured with `AMP_EMBEDDING_PROVIDER`; see [getting started](getting-started.md#5-choosing-an-embedding-provider). |
| `max_cell_size_bytes` | The largest serialized cell the server will accept. Enforced on create and on update; a larger cell is refused with `413 CELL_TOO_LARGE` before anything is written, and the number here is the number the check uses. |
| `retention_days` | How long a deleted cell is held before it may be purged (`30`, the spec's floor). Enforced by the storage layer: a `purge` inside the window is refused with `RetentionWindowError`, so the advertised number and the check cannot drift apart. This is a server-internal operation - neither purge nor this endpoint is a REST route. |
| `lifecycle_scheduler` | Whether decay runs on a timer, how often, and the admin route that triggers a pass on demand. That route is gated on `AMP_ADMIN_TOKEN`; with no token configured it answers `403 ADMIN_DISABLED` rather than being absent. |

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
| `scoring.importance` | float [0-1] | No | How important this memory is (default: `0.5`) |
| `scoring.confidence` | float [0-1] | No | Confidence in the memory's accuracy (default: `1.0`) |
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
  "id": "mem_01J5A3B7K9M2N4P6Q8R0S1T3V5",
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
curl http://localhost:8765/amp/v1/memories/mem_01J5A3B7K9M2N4P6Q8R0S1T3V5
```

**Path parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `memory_id` | string (ULID) | The ID returned when the cell was created |

**Response `200 OK`**

```json
{
  "amp_version": "0.1.0",
  "id": "mem_01J5A3B7K9M2N4P6Q8R0S1T3V5",
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
curl -X PATCH http://localhost:8765/amp/v1/memories/mem_01J5A3B7K9M2N4P6Q8R0S1T3V5 \
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

**Response `200 OK`** - the full updated cell

```json
{
  "amp_version": "0.1.0",
  "id": "mem_01J5A3B7K9M2N4P6Q8R0S1T3V5",
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

The record is not removable for at least 30 days (`retention_days` in [`GET /spec`](#get-spec)): physical removal is an internal operation, is refused inside that window, and is not exposed as a REST route in v0.1.0. See [Deletion semantics](https://github.com/glatinone/agent-memory-protocol/blob/master/spec/v0.1.0/lifecycle.md).

**Request**

```bash
curl -X DELETE http://localhost:8765/amp/v1/memories/mem_01J5A3B7K9M2N4P6Q8R0S1T3V5
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

Performs semantic (vector) search over active memory cells for a given owner. Results are ranked by a blend of vector similarity to the query (70%) and the cell's current decay score (30%, `spec/v0.1.0/lifecycle.md` §7 - `importance × confidence × e^(−decay_rate × Δt)`), so a fresher or more important cell can outrank a stale, lower-confidence one at similar relevance, but a highly relevant cell is never displaced by an unrelated-but-fresh one.

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
| `limit` | int [1-100] | No | Maximum number of results to return (default: `10`) |
| `include_stale` | bool | No | Shorthand to add `"stale"` to the status filter (default: `false`) |

**Response `200 OK`**

```json
{
  "results": [
    {
      "amp_version": "0.1.0",
      "id": "mem_01J5A3B7K9M2N4P6Q8R0S1T3V5",
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

## POST /lifecycle/run

Runs one decay pass (`LifecycleEngine.process_all()`) immediately, evaluating every cell and applying any `active → stale`, `stale → active`, or `stale → archived` transitions the decay scores call for. This is the same work the background scheduler does on its interval; it exists so an operator, an external cron, or a test can trigger a run on demand.

Because it mutates lifecycle state across the whole store, the endpoint is gated on the `AMP_ADMIN_TOKEN` environment variable. If that variable is unset the endpoint is **disabled** and returns `403`, rather than being left open.

**Request**

```bash
curl -X POST http://localhost:8765/amp/v1/lifecycle/run \
  -H "X-AMP-Admin-Token: $AMP_ADMIN_TOKEN"
```

**Headers**

| Header | Required | Description |
|--------|----------|-------------|
| `X-AMP-Admin-Token` | Yes | Must equal the server's `AMP_ADMIN_TOKEN` |

**Response `200 OK`**

```json
{
  "transitions": {
    "active_to_stale": 3,
    "stale_to_archived": 1,
    "stale_to_active": 0
  }
}
```

**Response fields**

| Field | Description |
|-------|-------------|
| `transitions` | Counts of cells moved, keyed by `<from>_to_<to>`. All keys are present even when zero. An empty object (`{}`) means the run failed and the error was logged. |

**Error responses**

| Status | `error.code` | Cause |
|--------|-------------|-------|
| `403` | `ADMIN_DISABLED` | `AMP_ADMIN_TOKEN` is not set on the server |
| `403` | `ACCESS_DENIED` | Header missing or does not match `AMP_ADMIN_TOKEN` |

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

A cell transitions to `stale` when its score falls below `0.3`. A `stale` cell returns to `active` once its score rises back to `0.3` or above - which a re-read (resetting `last_accessed_at`) or a `scoring` `PATCH` can do. A `stale` cell still below threshold transitions to `archived` after 30 days without an update. These transitions are applied by the background scheduler, or on demand via [`POST /lifecycle/run`](#post-lifecyclerun).

---

## Error response shape

All error responses use the following structure:

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Memory cell mem_01J5A3B7K9M2N4P6Q8R0S1T3V5 not found",
    "details": {}
  }
}
```

| Field | Description |
|-------|-------------|
| `error.code` | Machine-readable error code in `SCREAMING_SNAKE_CASE` |
| `error.message` | Human-readable description |
| `error.details` | Optional structured context (field errors, etc.) |
