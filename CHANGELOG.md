# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Lint, format and type gates.** Ruff and mypy are configured for both Python
  packages, a `quality` job runs them in CI, and `.pre-commit-config.yaml` runs
  the lint and format hooks before each local commit. Neither package had a
  linter or a type checker before this; the entries below are what the gates
  surfaced on the first run.
- A repo-root `ruff.toml`, so Python outside the two packages (`examples/`) is
  checked with the repository's rule set instead of Ruff's own fallback.
- `server/tests/test_error_shape.py`, pinning the error envelope on every
  endpoint and on every error helper.
- **A conformance suite any implementation can run** (`conformance/`). Test
  vectors written from the specification, plus a runner that reaches a server
  only over the wire: it imports nothing from `amp_server`, so it can be pointed
  at a third-party implementation. Four categories - `schema` (documents against
  the normative JSON Schema), `decay` (the score formula and the `0.3` stale
  threshold), `http_contract` (status codes, error envelopes, the archive-then
  delete flow) and `access_control` (the read and write decision for a policy
  matrix, checked through `GET`, `PATCH` and `POST /memories/search` at once).
  Install it as `amp-conformance`, write a machine-readable report with
  `--json`, and select a category with `--only`. A `"known_gap"` marker records
  a deviation without failing the run, and a gap that starts passing is reported
  as `unexpected_pass` so the list cannot rot. A `conformance` CI job runs the
  whole suite against the reference server on every push.
- `server/tests/test_spec_conformance.py`: the example the pydantic model
  publishes into the OpenAPI document is now validated against the spec schema,
  so `/docs` cannot show a document the protocol forbids.
- **A committed, tested API contract** (`spec/v0.1.0/openapi.json`), generated
  from the reference server. Committed rather than only served, so a change to
  the API surface shows up as a reviewable diff. Every route now declares the
  `401`, `403` and `409` responses it can return, which puts the protocol's error
  envelope in the contract instead of only in the code, and `DELETE
  /memories/{id}` declares the `204` it actually answers with. Two tests keep it
  honest: `server/tests/test_openapi_contract.py` fails when the committed paths
  stop matching the app, and `sdk/python/tests/test_openapi_contract.py` drives
  the real client through a recording adapter and fails when it calls a route the
  contract does not serve or omits a field the contract requires.
- **`GET /spec` is now true.** It advertised `max_cell_size_bytes` while nothing
  enforced it, so a client that sized its payloads against the advertised number
  could still store a cell far larger. The limit lives in `amp_server.limits`,
  the create and update paths measure the serialized cell against it before
  writing anything, and a larger cell is refused with `413 CELL_TOO_LARGE` in the
  same error envelope as every other protocol error.
  `server/tests/test_spec_capabilities.py` ties each advertised capability to a
  behaviour, and one of its tests proves the refusal is the limit doing the work
  by disabling the check and watching the same request succeed. The conformance
  suite gained a `spec_capabilities` category that checks a server against **its
  own** advertised values - the advertised maximum really is the maximum, an
  advertised `manual_run_endpoint` is a route that exists, and `/spec` and
  `/health` agree on the version - so it holds for any implementation, not only
  this one.
- **A choice of embedding provider** (`amp_server.embeddings`). The server used
  to embed with whatever Chroma picked, with no way to choose, which is fine for
  a demo and wrong for anyone with an embedding budget, a language MiniLM does
  not cover well, or a rule about where their text may go. `AMP_EMBEDDING_PROVIDER`
  now selects one: `default` keeps the local model, and `openai-compatible`
  points at any service speaking the OpenAI `/embeddings` API (OpenAI, Azure,
  Ollama, LM Studio, vLLM). A misconfigured provider stops the server from
  starting rather than falling back, because a silent fallback produces vectors
  nobody can search consistently. `GET /spec` reports the provider and the width
  of the vectors it produces, and the adapter hands Chroma finished vectors
  instead of an embedding function, so there is one place text becomes numbers.
  `httpx` moves from the dev extra to a runtime dependency for this.

- **A PostgreSQL + pgvector storage backend** (`amp_server.storage.postgres`),
  selected with `AMP_STORAGE_BACKEND=postgres`. Chroma is an embedded store:
  right for a reference deployment, and not what a team already running
  infrastructure has. The adapter keeps cells in a table with a `vector` column
  and an HNSW index (cosine, the same measure the Chroma adapter configures),
  creates its schema on start, and ships as the optional `amp-server[postgres]`
  extra. `server/docker-compose.yml` gained a `postgres` profile so
  `docker compose --profile postgres up -d` works out of the box.
  A second backend is only useful if it behaves like the first, so the search
  ranking (`amp_server.ranking`) and the record rules
  (`amp_server.storage.records`) moved into shared modules instead of being
  copied, and `tests/test_adapter_contract.py` runs one behaviour suite against
  both backends - including the test that they rank identical data in identical
  order. CI runs that suite against a real `pgvector/pgvector:pg16` service
  container with `AMP_REQUIRE_POSTGRES=1`, so the job cannot pass by skipping the
  Postgres half. `_get_raw` is now declared on `StorageAdapter`, which it had to
  be once more than one backend existed.

- **The 30-day retention window is now enforced instead of documented**
  (`amp_server.retention`). `spec/v0.1.0/lifecycle.md` §5 and RFC §5 make
  retention the server's responsibility - a deleted cell MUST be held for at
  least 30 days and `purge` is preconditioned on that window - but the rule lived
  in a docstring asking the *caller* to wait, so `purge()` would destroy a cell
  one second after `DELETE`. That is the retention-window bypass the RFC lists as
  a threat, and it destroys the audit evidence the window exists to keep. The rule
  now lives in one module used by both backends, and the refusal names the date
  the cell becomes purgeable. `GET /spec` advertises `retention_days`, tied to the
  same number the check uses.
- **A retention pass, opt-in** (`AMP_PURGE_RETENTION=1`, off by default).
  `LifecycleEngine.purge_expired()` removes deleted cells whose window has
  elapsed, and `POST /lifecycle/run` reports `purged` alongside `transitions`.
  Off by default on purpose: spec §6.3 sets a *minimum* retention, so holding a
  deleted cell longer is compliant, and a server that starts erasing data after an
  upgrade is a worse default than one that keeps it until asked. `docs/spec-explained.md`
  claimed a "background cleanup worker" that did not exist; it now describes what
  runs.

- **Optional API-key authentication** (`amp_server.auth` +
  `AMP_API_KEYS_FILE`). The spec carries agent identity in `X-AMP-Agent-ID` and
  defines no credential (RFC §6.1), so the header was an assertion: anyone who
  could reach the port could claim any agent id, and every access rule was decided
  from that claim. With a key store configured, the id must now be proven with a
  matching key in `X-AMP-API-Key`; the file stores `sha256:` digests rather than
  keys, and a wrong key, a missing key and an unknown agent id all answer the same
  `401 UNAUTHENTICATED` so the endpoints cannot enumerate agent ids. Off by
  default, so the spec's binding keeps working unchanged for anyone who has not
  opted in; a key store that cannot be read stops the server instead of silently
  falling back to trusting the header. This also closes `POST /memories`'s
  `identity.created_by` fallback whenever keys are configured - without that, the
  fallback would have been an authentication bypass. Both SDKs take the key as a
  constructor argument, and identity resolution now happens in one FastAPI
  dependency rather than in each handler, so a route cannot resolve an agent
  without proving it.

- **Paging on the listing endpoints, applied to cells the caller may read.**
  `GET /memories` (and its `/memories/query` alias) gained `offset`, and `limit`
  now counts cells the caller is allowed to read rather than cells examined. The
  old order - page the store, then filter by access - let a page come back short
  while readable cells sat just past the store-level limit, with no way for the
  caller to tell that from "that is all there is". Responses now report
  `returned` and `has_more` alongside the window used. The `total` field is gone
  from both listing and search responses: it was the size of the page just
  returned, and the search documentation described it as "total number of cells
  matched (may exceed `limit`)" - a number the code never produced. `GET /spec`
  advertises `max_page_size`, and a larger `limit` is refused rather than clamped.
- **`GET /memories/query` was unreachable.** FastAPI matches routes in
  registration order, and `/memories/{memory_id}` was declared before the static
  alias, so the alias was read as a memory id named "query" and answered `403`.
  It is now declared first, with a comment saying why the order matters; a test
  catches the next route that forgets.

### Changed
- **Every endpoint returns one error shape.** `PATCH /memories/{id}` answered a
  conflict with `{"detail": ...}` while `DELETE` answered with
  `{"error": {...}}`. Both SDKs read `body.error.code`, so a client hitting the
  PATCH conflict degraded to a generic `HTTP error 409`. Protocol errors now
  come from `amp_server.errors.AMPError` and a single exception handler renders
  them, which also lets the route handlers stay annotated `-> dict`.
- `amp_server` enums use `enum.StrEnum` instead of `class X(str, Enum)`.
- **The Python SDK's declared Python floor is now 3.10, and CI tests it.**
  `requires-python` claimed `>=3.8`, but `amp_client.exceptions` uses PEP 604
  unions in a signature without `from __future__ import annotations`, so the
  package could not be imported on 3.8 or 3.9 at all.
- `.gitattributes` normalizes line endings to LF in the repository, so the
  stored form no longer depends on a contributor's `core.autocrlf` setting.
- The demo scripts under `examples/` catch `requests.RequestException` rather
  than every `Exception`, so a genuine bug surfaces instead of printing a
  "server unreachable" message.

### Fixed
- Every documented example in `docs/getting-started.md` and
  `docs/api-reference.md` used a cell id without the `mem_` prefix, which the
  protocol's own schema forbids (`^mem_[0-9A-Z]{26}$`). Eleven examples across
  two files, including the curl commands and an error message, showed a document
  shape a reader could not have produced.
- The API reference's endpoint table omitted `GET /memories` and its
  `/memories/query` alias, so two of the ten documented operations were missing
  from the only place a reader looks for them.
- **`PATCH /memories/{id}` accepted lifecycle status changes the spec forbids.**
  `StorageAdapter.update()` applied whatever status it was handed, so a write
  could push a cell straight to `deleted` (bypassing the archived precondition
  and the DELETE semantics in spec §5) and an `archived` cell could be brought
  back to `active` even though §2 lists that as not permitted and 409.
  `check_status_transition()` in `amp_server.lifecycle` now enforces the two
  prohibitions in §2 and is called from the update path, which also makes the
  `409 INVALID_TRANSITION` branch on the route reachable for the first time.
  Both violations were found by the new conformance suite, not by reading the
  code. 19 tests in `server/tests/test_transitions.py`.
- The example in `MemoryCell.model_config`, which pydantic publishes into the
  OpenAPI document and therefore into `/docs`, carried an id without the `mem_`
  prefix and so was not a valid AMP document against the protocol's own schema.
- **`search()` applied a different read rule from the REST and MCP endpoints.**
  `storage/chroma.py` carried its own copy of the read check, and that copy
  skipped any `readable_by` entry equal to the literal string `"owner"` while
  `access_control.check_read_access` matched it like any other pattern. An agent
  whose id is `owner` could read a cell through `GET /memories/{id}` but never
  found it through `POST /memories/search`. Search now calls the shared rule and
  the duplicate is deleted; `test_access_control.py` runs the agent-by-policy
  matrix against both paths so they cannot drift apart again.
- The `except Exception` blocks that swallowed JSON-decoding failures in both
  SDKs now catch `ValueError`, so an unexpected error is no longer hidden
  behind a generic HTTP message.

### Removed
- The duplicate root `CONTRIBUTING.md`. Two divergent copies existed, nothing
  linked the root one, and GitHub prefers the `.github/` copy anyway; the
  merged content (including the quality gates above) lives in
  `.github/CONTRIBUTING.md`.

## [0.1.0] - 2026-10-03

First tagged release. The protocol specification (`v0.1.0`), the FastAPI
reference server, and the Python client SDK, released together.

### Added
- **The reference server now runs the decay engine on a schedule.** Closing the
  launch blocker: `LifecycleEngine.process_all()` was fully implemented and
  unit-tested but nothing ever called it, so a fresh `docker compose up -d`
  never transitioned a cell's status. It is now driven by a background asyncio
  task started from the FastAPI `lifespan` - on by default, cancelled cleanly on
  shutdown - answering the schedule `spec/v0.1.0/lifecycle.md` leaves
  implementation-defined.
  - `POST /amp/v1/lifecycle/run` triggers one pass on demand, gated on
    `AMP_ADMIN_TOKEN`; unset means the route is disabled (`403`), not open. This
    is what makes the run testable in CI and usable from an external cron or an
    operator.
  - `AMP_LIFECYCLE_ENABLED` (default `true`) and
    `AMP_LIFECYCLE_INTERVAL_SECONDS` (default `3600`) control the scheduler.
  - `GET /spec` now advertises the scheduler state and the manual-run endpoint.
  - A failing run is logged and swallowed, so one storage error cannot silently
    end all decay for the process lifetime.
  - `configure_logging()` - uvicorn configures only `uvicorn.*` loggers and
    never the root logger, so every `amp_server.*` log line (including the
    scheduler's start and run records, the only way to tell the scheduler is
    alive) went nowhere.
- First CI workflow (`.github/workflows/ci.yml`): separate `server` and `sdk`
  jobs, each on a Python 3.11/3.12 matrix, installing with dev extras and
  running the real test suite (`pytest`). Neither package had any CI before
  this.
- `sdk/pyproject.toml` now declares a `dev` extra (`pytest`, `pytest-asyncio`)
  and `[tool.pytest.ini_options] asyncio_mode = "auto"`. Previously, running
  `pytest` against the SDK's own test suite with only `pytest` installed
  failed 6 of 14 tests (`test_async_client.py`) with "async def functions are
  not natively supported" - a missing test dependency, not a code bug.

### Fixed
- **The LangChain integration was broken and nothing caught it.** `AMPMemory`
  subclassed `langchain_core.memory.BaseMemory`, which langchain-core 1.0
  removed. Because the import sat inside a `try/except ImportError`, the module
  still imported cleanly and the failure only appeared on construction, as
  `ImportError: langchain-core is required to use AMPMemory` - with
  langchain-core installed and working. Every published claim that AMP "includes
  native LangChain integration" was therefore false on current langchain-core,
  and no test covered it, so CI stayed green through it. This is the same class
  of dependency-drift failure as the `mcp<2` pin earlier in this file.
  Rewritten against the current interface: subclass `BaseChatMessageHistory`,
  implement `messages` / `add_message` / `clear`, keep `save_context` and
  `load_memory_variables` for the older chain API. The docstring records why,
  and `sdk/python/tests/test_langchain_memory.py` (15 tests) now covers
  ordering, prefix round-trip, multi-key context extraction, and the
  degrade-don't-raise behaviour when storage fails. The first test asserts the
  base class exists, so a future removal fails in CI rather than in a user's
  app. `sdk/README.md`'s example also used `ConversationChain`, removed in the
  same release; replaced with one that runs against the current API and was
  verified against a live server.
- **`stale → active` reactivation was implemented nowhere.** `spec/v0.1.0/
  lifecycle.md` §2 says a `stale` cell whose decay score is raised back above
  `0.3` - by a `scoring` `PATCH`, or by a `GET` that resets `last_accessed_at`
  - returns to `active` on the next engine run, and `docs/spec-explained.md`
  already told readers that. `LifecycleEngine.evaluate_cell()` had branches for
  `active → stale`, `stale → archived`, and terminal `deleted`, but none for
  this, so a `stale` cell stayed `stale` until it was archived. Added, with
  tests; `process_all()` now also always reports a `stale_to_active` count.
- Removed `apscheduler>=3.10.0` from `server/pyproject.toml`. It was declared
  but imported nowhere in the repo; the scheduler is a plain asyncio task, so
  the dependency was unused surface - and a needless CVE exposure in a
  security-conscious reference implementation.
- `docs/api-reference.md` described `GET /spec` as returning a "spec URL" and
  showed a response body without the `capabilities` fields the endpoint has
  returned since before this pass; corrected, and the new lifecycle endpoint
  and its auth are documented.
- `docs/faq.md` and `docs/index.md` told readers to wire decay into their own
  periodic job because the reference server did not run it on a timer. Made
  stale by the scheduler work above; both now describe the built-in default and
  the `AMP_LIFECYCLE_*` knobs.
- `README.md`'s top-line pitch and the Comparison table both described the
  decay-archival lifecycle as "automatic... out of the box," which was true
  of the *spec* but not of the reference server at the time - `LifecycleEngine
  .process_all()` was implemented and unit-tested, but nothing in
  `amp_server/main.py` called it, so a fresh `docker compose up -d` never
  transitioned a cell's status on its own. That pass reworded both spots to
  describe the state machine accurately and point at the FAQ instead of
  overclaiming the README readers see first, and corrected `docs/
  launch-checklist.md`'s stale test count and last-verified date. Superseded
  by the scheduler work above, which makes the automatic claim true of the
  running server rather than only of the spec.
- CI (`pip install -e .[dev]`, no lockfile) started failing with
  `ModuleNotFoundError: No module named 'mcp.server.fastmcp'` once the MCP
  Python SDK's 2.0.0 stable release renamed `FastMCP` to `MCPServer` and
  restructured `mcp.server` - a pervasive breaking rework, not a simple
  rename. The local dev environment never hit this because `uv.lock`
  already pinned `mcp==1.28.1`. Pinned `server/pyproject.toml`'s dependency
  to `mcp>=1.28.1,<2` rather than migrating `amp_server/mcp_server.py` to
  the new v2 API in the same pass. Verified with a clean `pip install`
  matching CI's exact steps: resolves `mcp==1.29.0`, all 57 tests pass.
  Migrating to the v2 API is real, separate work - see TODO.
- **`ChromaAdapter.search()` ranked purely by raw vector distance and never
  read `compute_decay_score()`, even though the decay formula
  (`spec/v0.1.0/lifecycle.md` §7 - `importance × confidence ×
  e^(−decay_rate × Δt)`) is the project's stated differentiator.** Confirmed
  by reading `search()` end to end: it queried Chroma for exactly
  `request.limit` results by similarity alone and never fetched distances,
  so two cells with near-identical text but very different freshness or
  importance came back in whatever order the vector index happened to
  return, and a stale, low-importance duplicate could rank above a fresh,
  important one. `search()` now queries the full collection, blends cosine
  similarity with `compute_decay_score()` (70% similarity / 30% decay, see
  `amp_server/storage/chroma.py`), and re-ranks before truncating to
  `limit` - relevance still dominates (an irrelevant-but-fresh cell does
  not outrank a genuinely relevant one), but a fresher/more important cell
  now breaks a near-tie in its favor. 2 new tests covering both directions
  (57 passing, was 55).
- `amp-server` console script (`server/pyproject.toml`) pointed at
  `amp_server.main:app` - the FastAPI ASGI app object itself, not a callable
  entry point - so running `amp-server` crashed immediately with
  `TypeError: FastAPI.__call__() missing 3 required positional arguments`.
  Added a real `main()` in `amp_server/main.py` that runs the app with
  `uvicorn.run(...)` (host/port overridable via `AMP_HOST`/`AMP_PORT`), and
  pointed the entry point at it. Verified end-to-end: the script now starts
  and serves `/amp/v1/health` and `/amp/v1/spec` correctly.
- `README.md`'s Build Status and PyPI version badges pointed at a GitHub org
  (`AMP-Protocol`) and a PyPI package (`amp-client`) that do not exist
  (verified via direct API/PyPI lookups - both 404). Removed both; replaced
  with a real, live CI badge (now that CI exists) and an explicit "not yet on
  PyPI, install from source" callout, matching the honesty bar the rest of
  the portfolio holds itself to.
- The Spec badge and the "Protocol Specification" section both linked to
  `../SPEC.md`, a file that has never existed in this repo (the real content
  lives in `spec/v0.1.0/`). Fixed both to point at the real files. Same wrong
  link existed in `docs/api-reference.md`'s and `docs/hn-submission.md`'s
  copy - only the actively-linked `docs/api-reference.md` was corrected this
  pass; the launch-only drafts are noted as a known gap below.
- `docs/getting-started.md` told readers to `git clone
  https://github.com/AMP-Protocol/amp.git` (nonexistent org) and `pip install
  amp-client` (nonexistent package) - corrected to the real clone URL and an
  install-from-source instruction.
- `docs/api-reference.md`'s documented `GET /spec` response
  (`{"amp_version", "spec_url"}`) didn't match what the endpoint actually
  returns (`{"amp_version", "capabilities": {...}}`, verified directly
  against the running server). Corrected.
- `examples/mcp-claude-desktop/mcp_config.json` set `AMP_STORAGE_PATH` (not a
  variable either `main.py` or `mcp_server.py` reads - both read
  `AMP_PERSIST_DIR`) and hardcoded a `cwd` pointing at a personal local path
  (`D:/50_Projects/...`) that would not exist on any other machine. Fixed the
  env var name and removed the machine-specific `cwd`.
- `examples/quickstart/README.md`, `examples/mcp-claude-desktop/README.md`,
  and `examples/multi-agent-demo/README.md` were all empty placeholder files
  (a single blank line). Filled in with real, accurate setup/run
  instructions for each example.
- Release readiness pass on the pre-launch drafts flagged as a known gap
  below: `docs/blog/launch-post.md` and `docs/hn-submission.md` both cloned
  `https://github.com/AMP-Protocol/amp.git` (nonexistent org) and linked
  `SPEC.md` at that org instead of the real `spec/v0.1.0/`. The blog post's
  code sample also imported `from amp import AMPClient` and called
  `client.memories.create(...)`/`client.memories.search(...)`, none of which
  exist. Corrected to the real `from amp_client import AMPClient` and
  `client.remember(...)`/`client.recall(...)`. Both drafts also described the
  Lifecycle & Decay Engine and (in the HN draft) a "cryptographic erasure by
  default" GDPR claim in stronger terms than the reference server actually
  implements; see the `LifecycleEngine` gap noted below. Reworded to
  describe the real decay formula and the spec's actual, narrower
  deletion-retention guarantee instead of overclaiming.
- `docs/faq.md` claimed the SDK was "fully available on PyPI" (`pip install
  amp-client`), directly contradicting `README.md`'s own "Not yet on PyPI"
  note two files over, and linked the same nonexistent `AMP-Protocol` org.
  Also claimed decay transitions happen automatically, which isn't true of
  the reference server as shipped (see below). All three corrected.
- `sdk/README.md` gave a bare `pip install amp-client` with no "not yet on
  PyPI" caveat, inconsistent with the root README and every other install
  section in the repo. Added the same caveat.
- `docs/launch-checklist.md` asserted things that weren't true when checked
  against the real repo: no PyPI badge exists (correctly, since it's not
  published), server tests currently number 55 (not the checklist's stale
  49), and the "automatic" decay/archival behavior isn't wired up (see
  below). Rewritten to state only what's actually verified, with the real
  gaps listed as open items instead of checked boxes.

### Known gaps (documented rather than silently carried)
- ~~`LifecycleEngine.process_all()` is fully implemented and unit-tested, but
  nothing in `amp_server/main.py` ever calls it.~~ **Resolved 2026-10-03** - see
  the scheduler entry under Added. The reference server now runs it on a
  configurable interval and exposes an admin-gated manual-run route.
- ~~`sdk/python/amp/` is a thin, unbuilt re-export shim that isn't wired into
  `sdk/pyproject.toml`'s build, so installing `amp-client` does not make
  `import amp` work.~~ **Resolved 2026-10-03** - the shim was deleted; it was
  referenced by nothing, and `sdk/amp_client/` is the real package.
