First tagged release of the Agent Memory Protocol: the `v0.1.0` specification,
the FastAPI reference server, the conformance suite, and the client SDKs,
released together.

**Documentation:** https://glatinone.github.io/agent-memory-protocol/

## What's in it

**Protocol specification (`spec/v0.1.0/`)**
- The `MemoryCell` JSON schema: content, identity, lifecycle, scoring, access
  policy, and provenance.
- A lifecycle state machine (`active` -> `stale` -> `archived` -> `deleted`)
  with an exponential decay formula driving the automatic transitions.
- RFC-AMP-001 covering the security model and threat considerations.

**Reference server (`server/`, Python/FastAPI)**
- Full memory CRUD plus semantic search, ranked by a blend of vector
  similarity (70%) and each cell's current decay score (30%).
- Per-cell access control (`readable_by` / `writable_by` with wildcards), and
  uniform `403` responses on deleted cells to prevent oracle probing.
- **Two storage backends.** ChromaDB is the default and needs no infrastructure;
  `AMP_STORAGE_BACKEND=postgres` keeps cells in PostgreSQL with `pgvector`
  instead, for deployments that already run one. Both are held to one behaviour
  suite, including that they rank identical data in identical order.
- **A chosen embedding provider.** `AMP_EMBEDDING_PROVIDER=default` uses the local
  model; `openai-compatible` points at any service speaking the OpenAI
  `/embeddings` API. A misconfiguration stops the server rather than falling back
  silently, because a silent fallback produces vectors nobody can search
  consistently.
- **The advertised capabilities are enforced, not claimed.** `GET /spec` reports
  the cell size limit, the storage backend, the embedding width, the retention
  window, the page ceiling and the scoring-edit budget, and a test ties each one
  to the behaviour it promises.
- **The 30-day deletion retention window is enforced.** The spec makes retention
  the server's job; a purge inside the window is refused, and names the date the
  cell becomes purgeable. Erasing deleted cells once that window passes is opt-in
  (`AMP_PURGE_RETENTION=1`), because the spec sets a minimum retention rather than
  a deadline.
- **Optional API-key authentication.** The spec carries identity in
  `X-AMP-Agent-ID` and defines no credential, so the header is trusted by default.
  Set `AMP_API_KEYS_FILE` and it must be proven with `X-AMP-API-Key`; the file
  holds `sha256:` digests rather than keys, and a wrong key, a missing key and an
  unknown agent id all answer the same `401`.
- **Pagination** on the listing endpoints and on search, applied to the cells the
  caller may read, with `has_more` rather than a count the server does not compute.
- **Rate-limited scoring edits** (RFC-AMP-001 §5): 5 per cell per hour by default,
  `429` with `Retry-After` beyond that, because a caller looping on `scoring` can
  hold a cell active past its relevance window.
- The decay engine runs on a background schedule by default. The interval is
  configurable (`AMP_LIFECYCLE_INTERVAL_SECONDS`, default 3600), and an
  admin-token-gated `POST /amp/v1/lifecycle/run` triggers a pass on demand for
  cron or ops use.
- Bundled MCP server (`amp-mcp`) so the server can be used as MCP tools.

**Conformance suite (`conformance/`)**
- 39 vectors an implementation can run against its own server:
  `amp-conformance --base-url https://your-server.example.com`.
- It imports nothing from the reference server and carries the normative JSON
  Schema, so it judges an implementation rather than comparing it to this one.
- One category measures a server against **its own** advertised numbers, so it
  holds for any implementation, not just this one.

**Machine-readable contract**
- `spec/v0.1.0/openapi.json` is generated from the server and committed, so an API
  change shows up as a reviewable diff. Two tests keep it honest, one on the
  server and one in the SDK.

**Client SDKs**
- Python (`sdk/amp_client/`): sync and async clients, plus a LangChain `AMPMemory`
  integration.
- Node (`sdk/node/`): zero dependencies, using the built-in `fetch`.
- Both take the optional API key and can page the listing and search endpoints.

**Examples** under `examples/`: a quickstart, an MCP `claude-desktop` config,
and a multi-agent demo where one agent is blocked by cell-level access policy.

248 server tests, 34 Python SDK tests, 24 Node tests and 39 conformance vectors.
CI runs lint, format and type gates across every package, Python 3.11 and 3.12,
Node 18, 20 and 22, the storage contract suite against a real PostgreSQL service
container, and the conformance suite against a live server.

## What's not here yet

Stated plainly rather than left for you to discover:

- **The SDKs are not published.** Install from this repo (`pip install -e sdk`, or
  copy `sdk/node`); the PyPI and npm packages are not out yet.
- **No hosted service.** Self-hosting via `docker compose up -d` is the only
  path today.
- **Python and Node only.** No Go or Rust clients.
- **Authentication is opt-in, and it is keys only.** With `AMP_API_KEYS_FILE`
  unset the memory endpoints trust the `X-AMP-Agent-ID` header, which is the
  binding the spec describes and is suitable for local development and
  single-tenant deployments, not for the open internet. Keys are a single shared
  secret per agent: no scopes, no expiry, no rotation, no OAuth or JWT.
- **Postgres support is verified in CI, not on your machine.** The machine this
  was developed on has no PostgreSQL, so the adapter's proof is the CI service
  container. Run `pytest tests/test_adapter_contract.py` with
  `AMP_TEST_POSTGRES_DSN` set to check it against yours.
- **The MCP binding's identity is shared by default.** One MCP server acts as one
  agent (`AMP_MCP_AGENT_ID`); unset, every MCP client pointed at the same store is
  the same agent, so per-agent `readable_by` is only meaningful once you set it -
  and run one server per agent.
- **Some state is per process.** The scoring-edit budget lives in the server
  process, so two processes over one database keep two budgets. The retention
  purge is likewise an in-process scheduled pass.
- **`POST /lifecycle/run` is all or nothing.** It runs one decay pass over every
  cell; there is no partial run and no per-owner scope.
- Two questions RFC-AMP-001 §8 defers to v0.2: negation in the `readable_by` /
  `writable_by` glob patterns, and a per-cell pluggable decay function.

## Install

```bash
git clone https://github.com/glatinone/agent-memory-protocol.git
cd agent-memory-protocol/server
docker compose up -d
```

Then see the [getting started guide](https://glatinone.github.io/agent-memory-protocol/getting-started/).

Feedback on the schema and the spec is very welcome in the issues.
