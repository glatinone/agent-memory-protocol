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

### Known gaps (not fixed this pass, documented rather than silently carried)
- `sdk/python/amp/` is a thin, unbuilt re-export shim (`from amp_client import
  ...`) that isn't wired into `sdk/pyproject.toml`'s build at all — installing
  `amp-client` does not make `import amp` work. `docs/blog/launch-post.md`
  (an unpublished draft, not linked from any live doc) uses `from amp import
  AMPClient` and a `client.memories.create(...)`-style API that doesn't match
  the real `AMPClient` (`client.remember(...)`/`recall`/`forget`). Needs a
  real design decision (wire up the `amp` alias, or delete it) before the
  blog draft can be trusted — out of scope for this pass since it's not part
  of the live documentation surface a user would actually reach today.
- `docs/hn-submission.md`, `docs/devto-tags.md`, `docs/launch-checklist.md`
  are pre-launch drafts, also unlinked from any live doc, that still
  reference the nonexistent `AMP-Protocol` org/`SPEC.md` path. Same reasoning
  as above — will need a pass before an actual launch, not before.
