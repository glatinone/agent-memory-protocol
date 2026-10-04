# AMP Launch Checklist

This checklist tracks whether the Agent Memory Protocol (AMP) repository and
associated launch material are actually ready for a public launch attempt,
not just present, but verified against the real code and docs. Last verified
2026-10-03.

## 1. Documentation & Specification
- [x] Top-level `README.md` complete and landing-page ready
- [x] Badges configured: CI status, license, spec version (no PyPI badge;
      not published yet, see item below)
- [x] Mermaid architecture diagram present and matches the real components
- [x] Protocol specification complete at `spec/v0.1.0/` (there is no root
      `SPEC.md`; every doc link now points at the real path)
- [x] MkDocs site configuration (`mkdocs.yml` at the repo root) set up, nav
      matches existing files, and the site is built and deployed to GitHub
      Pages by `.github/workflows/docs.yml` (live at
      https://glatinone.github.io/agent-memory-protocol/, verified 2026-10-02).
      Repo-internal material (`blog/`, `hn-submission.md`, `devto-tags.md`,
      `launch-checklist.md`) is excluded from the published site.
- [x] `getting-started.md` verified against the real server/SDK API and repo
      paths
- [x] `faq.md` corrected 2026-07-28: no longer claims the SDK is on PyPI, no
      longer claims decay transitions happen automatically without a
      scheduler, wrong org links fixed
- [x] `spec-explained.md` written, explaining MemoryCells, state
      transitions, decay score math, and access policies

## 2. Code Implementations
- [x] Reference server (`server/`) complete with FastAPI and ChromaDB
      integration
- [x] All server tests pass: 70 passing (`pytest -v`, verified
      2026-10-03; the checklist previously said 57, then 55)
- [x] Python SDK client (`sdk/amp_client/`) complete with sync, async, and
      LangChain support, 29 tests passing
      (was 14; +15 covering the LangChain integration, which had none and had
      silently broken - see the CHANGELOG entry for the `BaseMemory` removal)
- [x] Node.js SDK client (`sdk/node/`) added 2026-10-03: dependency-free
      (Node 18+ `fetch`, JSDoc types, no build step), 16 tests passing
      against a live server. CI runs it on Node 18/20/22 with the real
      server booted, so the integration half does not skip.
- [x] Multi-agent demo (`examples/multi-agent-demo/`) implemented and runs
      successfully
- [x] Local directories mapped for persistence via `AMP_PERSIST_DIR`
- [x] `ChromaAdapter.search()` now blends vector similarity with the decay
      score (70/30) instead of ranking on raw similarity alone, so search
      results actually reflect the freshness/importance model described in
      the spec and marketing drafts (shipped 2026-07-31, 2 new tests)
- [x] CI dependency drift caught and fixed: the MCP Python SDK's 2.0.0
      stable release broke `server`'s install (`mcp.server.fastmcp` no
      longer exists); pinned to `mcp>=1.28.1,<2` (2026-07-31). CI verified
      green on `master` since
- [x] `LifecycleEngine.process_all()` (the decay → stale → archived state machine)
      is now run on a schedule by the reference server: a background asyncio
      task started from the FastAPI `lifespan`, on by default, with an
      admin-token-gated `POST /amp/v1/lifecycle/run` for on-demand runs and a
      configurable interval (`AMP_LIFECYCLE_INTERVAL_SECONDS`, default 3600).
      Wired and verified 2026-10-03; the `active → stale`, `stale → active`,
      and `stale → archived` transitions now actually happen in a running
      deployment. 13 new tests (70 passing, was 57).
- [x] `sdk/python/amp/` shim removed (2026-10-03). It was four dead re-export
      files referenced by nothing; `sdk`'s installable package was always
      `sdk/amp_client/`, which is what the tests and docs use.

## 3. Launch Marketing Material
- [x] Draft blog post written (`docs/blog/launch-post.md`), corrected
      2026-07-28: real repo URL and clone path, real SDK import/method
      names (`amp_client.remember`/`.recall`, not `client.memories.create`/
      `.search`), real "not yet on PyPI" install step, real spec path,
      decay description no longer overclaims automatic scheduling
- [x] Live multi-agent console run output embedded as verification log
- [x] Draft "Show HN" submission text (`docs/hn-submission.md`), corrected
      2026-07-28: same org/link/decay fixes as the blog post, GDPR claim
      narrowed from "cryptographic erasure by default" to what the spec and
      reference server actually implement (30-day retention window;
      cryptographic erasure is an optional implementation strategy the spec
      allows, not something the reference server does today)
- [x] Recommended dev.to tags mapped (`docs/devto-tags.md`)
- [ ] These are still drafts, not a scheduled launch. Re-read them once
      more immediately before actually publishing, in case the SDK or
      server API shifts again before then.
- [x] Drafts re-checked against the server (2026-10-04) after the hardening
      chain landed. Corrected two claims that had become false - "ChromaDB is
      the only storage backend" and "no auth on the memory endpoints" - and the
      "what's next" list, which still promised a Postgres adapter and stronger
      auth as future work. Release notes for v0.1.0 carried the same stale
      claims and were rewritten in the same pass.

## 4. Community & Contribution Assets
- [x] GitHub bug report template (`.github/ISSUE_TEMPLATE/bug_report.md`)
- [x] GitHub feature request template
      (`.github/ISSUE_TEMPLATE/feature_request.md`)
- [x] GitHub RFC template (`.github/ISSUE_TEMPLATE/rfc.md`)
- [x] Contribution guide (`.github/CONTRIBUTING.md`) covering dev
      environment setup, pytest verification, type hinting, and spec RFC
      changes
- [x] Pull Request template (`.github/PULL_REQUEST_TEMPLATE.md`)
- [x] MIT `LICENSE` file present at the root

## 5. Build Verification
- [x] No syntax errors in any project Python file (`python -m py_compile`
      across `server/amp_server` and `sdk/amp_client`, verified 2026-07-28)
- [x] No broken internal markdown links in `README.md` (verified
      2026-07-27 against the live-rendered page's anchors)

## Still blocking an actual launch

1. Kiel's own call on whether this project gets ongoing development or
   stays at its current, honestly-documented depth (see
   `projects/agent-memory-protocol.md` roadmap). That decision should
   land before any of this launch material actually gets published.
2. The launch drafts (`docs/blog/launch-post.md`, `docs/hn-submission.md`)
   were written before the decay scheduler was wired up and before the
   `stale → active` fix; re-read them immediately before publishing, since
   the scheduler changes what they should say about decay.
