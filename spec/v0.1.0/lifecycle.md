# AMP Lifecycle Specification — v0.1.0

**Spec reference:** §6 (states), §7 (decay), §8 (archival), §6.3 (deletion)

---

## 1. State Table

| Status | Definition | Assigned When |
|--------|-----------|---------------|
| `active` | Cell is operational and included in all search results. | On creation; or on PATCH that restores a `stale` cell's score above threshold. |
| `stale` | Decay score has fallen below the stale threshold. Cell is excluded from default search results but retrievable by ID. | Automatically by `LifecycleEngine` when `decay_score < 0.3`. |
| `archived` | Cell has been stale without update for ≥ 30 days. Excluded from search. Data is retained but deprioritized in storage. | Automatically by `LifecycleEngine` when `stale_age_days ≥ 30`. |
| `deleted` | Cell has been soft-deleted. Excluded from all search results. Returns `403` on read/write attempts. Physical data is retained for the 30-day GDPR audit window. | Via `DELETE /amp/v1/memories/{id}` (manual, requires write access). Only valid from `archived`. |

Terminal statuses: `deleted`. The `LifecycleEngine` skips cells with status `archived` or `deleted` during `process_all`.

---

## 2. Transition Table

```
active ──[auto: score < 0.3]──► stale ──[auto: stale_age ≥ 30d]──► archived ──[manual: DELETE]──► deleted ──[admin: purge]──► (removed)
  ▲                                │
  └──[manual: PATCH scoring]───────┘
```

| From | To | Trigger | Condition | Invalid Transition Response |
|------|----|---------|-----------|----------------------------|
| `active` | `stale` | Automatic (`LifecycleEngine.process_all`) | `decay_score < 0.3` | — |
| `stale` | `archived` | Automatic (`LifecycleEngine.process_all`) | `stale_age_days ≥ 30` | — |
| `archived` | `deleted` | Manual (`DELETE /amp/v1/memories/{id}`) | Caller has write access | `409 INVALID_TRANSITION` if not from `archived` |
| `deleted` | *(removed)* | Admin only (`purge`) | Status is `deleted` and 30-day retention window has elapsed | `409 INVALID_TRANSITION` if status is not `deleted` |
| `stale` | `active` | Manual (`PATCH /amp/v1/memories/{id}`) | Updating `scoring` fields raises the decay score above `0.3` on the next `LifecycleEngine` run | — |
| `deleted` | any | — | **Not permitted.** `deleted` is terminal. | `403 ACCESS_DENIED` |
| `archived` | `active` / `stale` | — | **Not permitted** via the API. Re-create the cell if needed. | `409 INVALID_TRANSITION` |

**Notes:**
- The `LifecycleEngine` evaluates cells by calling `process_all`, which is expected to run on a scheduled interval (implementation-defined).
- Manual `PATCH` of `lifecycle.status` to `deleted` is **not permitted**; use the `DELETE` endpoint.
- Attempting any operation on a `deleted` cell via the REST API returns `403 ACCESS_DENIED` regardless of ACL state (oracle-attack prevention per §8.4).

---

## 3. Decay Formula

### Formula

```
decay_score = importance × confidence × e^(−decay_rate × Δt)
```

### Variable definitions

| Variable | Source | Type | Description |
|----------|--------|------|-------------|
| `importance` | `scoring.importance` | float [0.0, 1.0] | Subjective weight assigned to this memory. |
| `confidence` | `scoring.confidence` | float [0.0, 1.0] | Confidence in the accuracy of the memory content. |
| `decay_rate` | `scoring.decay_rate` | float ≥ 0.0 | Per-day exponential decay coefficient. Set to `0.0` for non-decaying memories. |
| `Δt` | `lifecycle.last_accessed_at` if set, else `lifecycle.created_at` | float (days) | Days elapsed since the cell was last accessed or created. Accessing a cell via `GET /memories/{id}` resets this clock. |

### Default values

| Variable | Default |
|----------|---------|
| `importance` | `0.5` |
| `confidence` | `1.0` |
| `decay_rate` | `0.01` |

### Stale threshold

A cell transitions to `stale` when:

```
decay_score < 0.3
```

### Example: 30-day-old memory with default scoring

```
importance  = 0.5   (default)
confidence  = 1.0   (default)
decay_rate  = 0.01  (default)
Δt          = 30 days

decay_score = 0.5 × 1.0 × e^(−0.01 × 30)
            = 0.5 × e^(−0.3)
            = 0.5 × 0.7408
            = 0.3704
```

**Result:** `0.3704 > 0.3` → cell remains `active`.

With default scoring, a cell reaches the stale threshold at:

```
0.5 × e^(−0.01 × t) = 0.3
e^(−0.01t) = 0.6
t = −ln(0.6) / 0.01 ≈ 51.1 days
```

### Half-life

At `decay_rate = 0.01`, the half-life of the decay score is `ln(2) / 0.01 ≈ 69.3 days`.

---

## 4. Archival Rules

A cell in `stale` status transitions to `archived` when **both** conditions are met:

| # | Condition | Reference |
|---|-----------|-----------|
| 1 | `lifecycle.status == "stale"` | Status check in `LifecycleEngine.evaluate_cell` |
| 2 | `(now − reference) ≥ 30 days` where `reference = last_updated_at` if set, else `created_at` | `ARCHIVE_STALE_DAYS = 30` in `lifecycle.py` |

**Note on reference timestamps:**
- The **decay score** clock resets on access (`last_accessed_at`).
- The **archival age** clock resets only on content or metadata updates (`last_updated_at`). Accessing a stale cell without modifying it does not delay archival.

Archived cells are **not evaluated further** by `LifecycleEngine.process_all` and cannot transition back to `active` or `stale` through the standard API.

---

## 5. Deletion Semantics

### Soft-delete (standard)

Initiated via `DELETE /amp/v1/memories/{id}`. The operation:

1. Verifies the caller has write access (`writable_by` or is `created_by` / `owner_id`).
2. Verifies the current status is `archived`. Any other status raises `409 INVALID_TRANSITION`.
3. Sets `lifecycle.status = "deleted"`.
4. Does **not** remove physical data from storage.

After soft-delete:
- `GET /memories/{id}` → `403 ACCESS_DENIED`
- `PATCH /memories/{id}` → `403 ACCESS_DENIED`
- `POST /memories/search` → cell excluded from results
- Direct storage lookup (`_get_raw`) → cell remains readable internally (used by `LifecycleEngine`)

### Purge (physical removal)

The `purge` operation is not exposed as a REST endpoint in v0.1.0. It is available as an internal storage method (`StorageAdapter.purge`) for administrative use and automated retention jobs.

Preconditions:
- `lifecycle.status == "deleted"` (enforces `409 INVALID_TRANSITION` otherwise)
- The 30-day GDPR retention window has elapsed since deletion

After purge, the cell is irrecoverably removed from the storage backend.

### 30-day retention window

Per spec §6.3, all deleted cells MUST be retained in storage for a minimum of 30 days after the `DELETE` call. This window exists to:

- Support GDPR Article 17 audit requirements
- Allow operators to recover accidentally deleted cells within the window
- Enable forensic review in the event of a security incident

Retention enforcement is the responsibility of the server implementation, not the protocol client.

### Cryptographic erasure

For implementations storing sensitive memory content encrypted at rest, cryptographic erasure (key destruction) MAY be performed at soft-delete time as an alternative to delayed physical purge. Implementations that use cryptographic erasure MUST still retain the cell shell (id, lifecycle metadata, access policy) for the 30-day window to satisfy audit requirements. The `content.text` and `content.metadata` fields MAY be replaced with a tombstone marker after key destruction.
