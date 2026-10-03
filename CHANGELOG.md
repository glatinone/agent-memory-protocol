# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
