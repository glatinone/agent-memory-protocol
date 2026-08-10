# RFC-AMP-001: Agent Memory Protocol Core Specification

- **Status:** Draft
- **Version referenced:** v0.1.0
- **Supersedes:** none
- **Related:** [`spec/v0.1.0/memory-cell.schema.json`](../v0.1.0/memory-cell.schema.json), [`spec/v0.1.0/lifecycle.md`](../v0.1.0/lifecycle.md)

## 1. Abstract

AMP (Agent Memory Protocol) defines an HTTP-native, framework-agnostic wire format and lifecycle model for storing, retrieving, and sharing structured memory between AI agents. This RFC consolidates the v0.1.0 schema and lifecycle specs into a single reference document, and adds the threat model and transport binding detail not yet covered elsewhere in the spec.

## 2. Motivation

Every agent framework (LangChain, CrewAI, custom orchestration) currently reinvents memory storage as an internal implementation detail: incompatible schemas, no shared access-control model, no standard decay/forgetting semantics, and no way for two agents built on different stacks to read the same memory. MCP solved this problem for *tool calling* — a standard interface any client can speak to any server. AMP does the same for *memory*: one schema, one lifecycle state machine, one access-control model, addressable over HTTP or bound as MCP tools.

## 3. Memory Cell Schema (Normative)

A Memory Cell is the atomic unit of AMP storage. The canonical schema is [`memory-cell.schema.json`](../v0.1.0/memory-cell.schema.json) (JSON Schema draft-07); this section summarizes its structure.

### 3.1 Required top-level fields

| Field | Type | Description |
|---|---|---|
| `amp_version` | string | Spec version this cell conforms to (`"0.1.0"`) |
| `id` | string | ULID prefixed `mem_`, pattern `^mem_[0-9A-Z]{26}$` |
| `type` | enum | Cognitive category: `episodic`, `semantic`, `procedural` |
| `content` | object | Payload — requires `text` (string, non-empty); optional `metadata` (arbitrary key-value) |
| `identity` | object | Ownership — requires `owner_id`, `owner_type` (`user`\|`agent`\|`organization`); optional `created_by`, `session_id` |
| `lifecycle` | object | Temporal state — requires `created_at`; see §4 |

### 3.2 Optional structured fields

| Field | Purpose |
|---|---|
| `scoring` | Decay inputs: `importance` [0,1], `confidence` [0,1], `decay_rate` (≥0, default `0.01`), `access_count` |
| `access_policy` | ACL: `readable_by` / `writable_by` (agent-ID glob patterns), `public` (bool) |
| `provenance` | Origin metadata: `source_type` (`conversation`\|`document`\|`inference`\|`user_explicit`), `source_ref`, `extraction_method` |

`additionalProperties: false` is enforced at every object level — clients MUST NOT rely on undeclared fields surviving a round-trip.

## 4. Lifecycle States (Normative — see [lifecycle.md](../v0.1.0/lifecycle.md) for full detail)

The implemented state set is **`active`, `stale`, `archived`, `deleted`** — not a separate "decayed" state. Decay is a continuous *score*, computed per the formula below, that *drives* the `active → stale` transition; it is not itself a lifecycle status. This RFC uses the implemented terminology rather than the informal "Active/Stale/Archived/Decayed" phrasing sometimes used colloquially, to stay consistent with the schema's `lifecycle.status` enum and avoid introducing a fifth state that doesn't exist in any implementation.

| Status | Meaning | Terminal? |
|---|---|---|
| `active` | Included in search results | No |
| `stale` | `decay_score < 0.3`; excluded from default search, retrievable by ID | No |
| `archived` | Stale for ≥30 days; excluded from search entirely | No |
| `deleted` | Soft-deleted; `403` on read/write; retained 30 days for GDPR audit | Yes |

**Decay formula:**

```
decay_score = importance × confidence × e^(−decay_rate × Δt)
```

where `Δt` is days since `last_accessed_at` (or `created_at` if never accessed). Default scoring (`importance=0.5, confidence=1.0, decay_rate=0.01`) reaches the `stale` threshold (`0.3`) at ≈51 days; half-life ≈69.3 days.

Transitions `active→stale` and `stale→archived` are automatic (`LifecycleEngine.process_all`, run on an implementation-defined schedule). `archived→deleted` is manual via `DELETE`, requires write access, and is only valid from `archived` (`409 INVALID_TRANSITION` otherwise). `deleted` is terminal via the API; physical purge is an internal, admin-only operation gated on the 30-day retention window.

## 5. Threat Vectors & Mitigations

| Threat | Description | Mitigation (spec-level) |
|---|---|---|
| **Memory poisoning** | An agent with write access injects a fabricated memory cell (e.g. false `semantic` fact) intended to be later retrieved and trusted by a different agent or the same agent in a future session | `identity.created_by` and `provenance` fields make injected memories attributable; `access_policy.writable_by` scoping limits which agents can write into a given owner's memory space. Consuming agents SHOULD treat `provenance.source_type == "inference"` memories with lower trust than `user_explicit`. |
| **Unauthorized retrieval / cross-tenant leakage** | An agent ID pattern in `readable_by` is too broad (e.g. an overly generous wildcard like `agent-*`), or `public: true` is set on a cell that shouldn't be | Access control is per-cell, not per-collection — every read/write MUST be checked against `access_policy` even for cells returned by search. `public` defaults to `false`; implementations MUST NOT default it to `true`. |
| **Oracle attack against deleted cells** | Probing whether a `deleted` cell exists by observing different error responses for "not found" vs. "exists but deleted" | Per spec §8.4, any operation on a `deleted` cell returns `403 ACCESS_DENIED` uniformly, regardless of the caller's ACL standing — the same response whether the cell never existed or existed and was deleted. |
| **Decay-score manipulation** | A caller repeatedly PATCHes `scoring` fields to keep a cell artificially `active` past its intended relevance window, or to force premature archival of a competing memory | `PATCH` updating `scoring` only affects the *next* `LifecycleEngine.process_all` evaluation, not an immediate status flip — bounds the rate of manipulation to the engine's run cadence. Implementations SHOULD rate-limit `scoring` PATCH frequency per cell. |
| **Retention-window bypass** | A caller attempts to force early physical purge of a `deleted` cell within the 30-day GDPR window to destroy evidence | Purge is not exposed via the REST API in v0.1.0 (`StorageAdapter.purge` is internal/admin-only) and is preconditioned on the 30-day window having elapsed, enforced server-side. |

## 6. Transport & Protocol Bindings

AMP defines a payload/lifecycle model, not a single transport. Two bindings are implemented in the reference server (`server/amp_server/`):

### 6.1 HTTP REST (`server/amp_server/main.py`)
Standard REST verbs against `/amp/v1/memories`: `POST` (create), `GET /{id}` (read, resets decay clock), `PATCH /{id}` (update scoring/content), `POST /search` (query), `DELETE /{id}` (soft-delete, requires `archived` status). Authentication/agent identity is carried via the `X-AMP-Agent-ID` header, which becomes `identity.created_by` when unset explicitly.

### 6.2 MCP Tool Binding (`server/amp_server/mcp_server.py`)
The same operations are exposed as MCP tools, so any MCP-speaking agent client can read/write AMP memory without a separate HTTP client — memory becomes just another tool call in the same protocol surface the agent already uses for everything else. This is the binding that makes AMP composable with MCP rather than a competing standard.

### 6.3 SDK bindings
Reference clients: `sdk/amp_client` (sync + async Python), with a LangChain integration (`amp_client/integrations/langchain.py`) demonstrating framework interop as the core motivation in practice.

## 7. Non-Goals (v0.1.0)

- AMP does not define a vector index format or embedding model — `ChromaAdapter` (`server/amp_server/storage/chroma.py`) is one storage backend choice, not a protocol requirement. Other `StorageAdapter` implementations are expected.
- AMP does not define cross-server federation (an agent querying multiple independent AMP servers as one namespace) — out of scope for v0.1.0, noted here as a likely v0.2 direction.

## 8. Open Questions for v0.2

- Should `readable_by`/`writable_by` glob patterns support negation, or only positive matches?
- Should the decay formula be pluggable per-cell (a `decay_function` field) rather than fixed exponential?
