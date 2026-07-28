# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project has not yet made a tagged release; entries below are grouped as
`[Unreleased]` until the first one ships.

## [Unreleased]

### Added
- First CI workflow (`.github/workflows/ci.yml`): separate `server` and `sdk`
  jobs, each on a Python 3.11/3.12 matrix, installing with dev extras and
  running the real test suite (`pytest`). Neither package had any CI before
  this.
- `sdk/pyproject.toml` now declares a `dev` extra (`pytest`, `pytest-asyncio`)
  and `[tool.pytest.ini_options] asyncio_mode = "auto"`. Previously, running
  `pytest` against the SDK's own test suite with only `pytest` installed
  failed 6 of 14 tests (`test_async_client.py`) with "async def functions are
  not natively supported" — a missing test dependency, not a code bug.

### Fixed
- `amp-server` console script (`server/pyproject.toml`) pointed at
  `amp_server.main:app` — the FastAPI ASGI app object itself, not a callable
  entry point — so running `amp-server` crashed immediately with
  `TypeError: FastAPI.__call__() missing 3 required positional arguments`.
  Added a real `main()` in `amp_server/main.py` that runs the app with
  `uvicorn.run(...)` (host/port overridable via `AMP_HOST`/`AMP_PORT`), and
  pointed the entry point at it. Verified end-to-end: the script now starts
  and serves `/amp/v1/health` and `/amp/v1/spec` correctly.
- `README.md`'s Build Status and PyPI version badges pointed at a GitHub org
  (`AMP-Protocol`) and a PyPI package (`amp-client`) that do not exist
  (verified via direct API/PyPI lookups — both 404). Removed both; replaced
  with a real, live CI badge (now that CI exists) and an explicit "not yet on
  PyPI, install from source" callout, matching the honesty bar the rest of
  the portfolio holds itself to.
- The Spec badge and the "Protocol Specification" section both linked to
  `../SPEC.md`, a file that has never existed in this repo (the real content
  lives in `spec/v0.1.0/`). Fixed both to point at the real files. Same wrong
  link existed in `docs/api-reference.md`'s and `docs/hn-submission.md`'s
  copy — only the actively-linked `docs/api-reference.md` was corrected this
  pass; the launch-only drafts are noted as a known gap below.
- `docs/getting-started.md` told readers to `git clone
  https://github.com/AMP-Protocol/amp.git` (nonexistent org) and `pip install
  amp-client` (nonexistent package) — corrected to the real clone URL and an
  install-from-source instruction.
- `docs/api-reference.md`'s documented `GET /spec` response
  (`{"amp_version", "spec_url"}`) didn't match what the endpoint actually
  returns (`{"amp_version", "capabilities": {...}}`, verified directly
  against the running server). Corrected.
- `examples/mcp-claude-desktop/mcp_config.json` set `AMP_STORAGE_PATH` (not a
  variable either `main.py` or `mcp_server.py` reads — both read
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

### Known gaps (not fixed this pass, documented rather than silently carried)
- **`LifecycleEngine.process_all()`, the `active`→`stale`→`archived` decay
  state machine, is fully implemented and unit-tested, but nothing in
  `amp_server/main.py` ever calls it.** The spec (`spec/v0.1.0/lifecycle.md`)
  explicitly leaves the run schedule "implementation-defined," and the
  reference server doesn't define one: no background task, no scheduled
  job, no route that triggers it. A fresh `docker compose up -d` will never
  transition a cell's status on its own. This means the "automatic decay"
  language in the README/FAQ/marketing drafts was accurate to the *spec*
  but not to *this running server* until someone wires `process_all()` into
  a scheduler (an asyncio task in the FastAPI `lifespan`, an admin endpoint,
  or an external cron). Docs were corrected this pass to describe the real
  behavior; the code itself was not touched. Scheduling it is a real design
  decision (interval, whether it should be on by default, how to make it
  testable) and out of scope for a docs-only pass. See
  `docs/launch-checklist.md`.
- `sdk/python/amp/` is a thin, unbuilt re-export shim (`from amp_client import
  ...`) that isn't wired into `sdk/pyproject.toml`'s build at all — installing
  `amp-client` does not make `import amp` work. Needs a real design decision
  (wire up the `amp` alias, or delete it); unrelated to the doc fixes above.
