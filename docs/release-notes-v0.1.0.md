First tagged release of the Agent Memory Protocol: the `v0.1.0` specification,
the FastAPI reference server, and the Python client SDK, released together.

**Documentation:** https://glatinone.github.io/agent-memory-protocol/

## What's in it

**Protocol specification (`spec/v0.1.0/`)**
- The `MemoryCell` JSON schema: content, identity, lifecycle, scoring, access
  policy, and provenance.
- A lifecycle state machine (`active` -> `stale` -> `archived` -> `deleted`)
  with an exponential decay formula driving the automatic transitions.
- RFC-AMP-001 covering the security model and threat considerations.

**Reference server (`server/`, Python/FastAPI, ChromaDB storage)**
- Full memory CRUD plus semantic search, ranked by a blend of vector
  similarity (70%) and each cell's current decay score (30%).
- Per-cell access control (`readable_by` / `writable_by` with wildcards), and
  uniform `403` responses on deleted cells to prevent oracle probing.
- The decay engine runs on a background schedule by default. The interval is
  configurable (`AMP_LIFECYCLE_INTERVAL_SECONDS`, default 3600), and an
  admin-token-gated `POST /amp/v1/lifecycle/run` triggers a pass on demand for
  cron or ops use.
- Bundled MCP server (`amp-mcp`) so the server can be used as MCP tools.

**Python SDK (`sdk/amp_client/`)**
- Sync and async clients, plus a LangChain `AMPMemory` integration.

**Examples** under `examples/`: a quickstart, an MCP `claude-desktop` config,
and a multi-agent demo where one agent is blocked by cell-level access policy.

70 server tests and 14 SDK tests pass on Python 3.11 and 3.12.

## What's not here yet

Stated plainly rather than left for you to discover:

- **The SDK is not on PyPI.** Install from this repo (`pip install -e sdk`).
- **No hosted service.** Self-hosting via `docker compose up -d` is the only
  path today.
- **Python only.** No Node.js, Go, or Rust clients yet.
- **ChromaDB is the only storage backend** wired up.
- **No authentication on the memory endpoints.** Access control is per-cell via
  `access_policy` and the `X-AMP-Agent-ID` header, which is a trust-the-caller
  model suitable for local development and single-tenant deployments, not for
  exposing the server to the open internet. The protocol spec allows stronger
  implementations; the reference server keeps it simple on purpose.

## Install

```bash
git clone https://github.com/glatinone/agent-memory-protocol.git
cd agent-memory-protocol/server
docker compose up -d
```

Then see the [getting started guide](https://glatinone.github.io/agent-memory-protocol/getting-started/).

Feedback on the schema and the spec is very welcome in the issues.
