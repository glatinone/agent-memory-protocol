# AMP Launch Checklist

This checklist tracks whether the Agent Memory Protocol (AMP) repository and
associated launch material are actually ready for a public launch attempt,
not just present, but verified against the real code and docs. Last verified
2026-07-28.

## 1. Documentation & Specification
- [x] Top-level `README.md` complete and landing-page ready
- [x] Badges configured: CI status, license, spec version (no PyPI badge;
      not published yet, see item below)
- [x] Mermaid architecture diagram present and matches the real components
- [x] Protocol specification complete at `spec/v0.1.0/` (there is no root
      `SPEC.md`; every doc link now points at the real path)
- [x] MkDocs site configuration (`docs/mkdocs.yml`) set up, nav matches
      existing files
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
- [x] All server tests pass: 55 passing (`uv run pytest`, verified
      2026-07-28; the checklist previously said 49, which was stale)
- [x] Python SDK client (`sdk/amp_client/`) complete with sync, async, and
      LangChain support, 14 tests passing
- [x] Multi-agent demo (`examples/multi-agent-demo/`) implemented and runs
      successfully
- [x] Local directories mapped for persistence via `AMP_PERSIST_DIR`
- [ ] `LifecycleEngine.process_all()` (the decay to stale to archived state
      machine) is implemented and unit-tested, but nothing in `main.py`
      ever calls it. The spec itself says the run schedule is
      "implementation-defined," and the reference server doesn't define
      one yet. Until this is wired into a periodic job, decay transitions
      described in the README/FAQ don't actually happen in a running
      deployment. Needs a design decision (background asyncio task in the
      FastAPI lifespan, an admin endpoint, an external cron hitting a new
      route) before launch claims "automatic" decay without qualification.
- [ ] `sdk/python/amp/` is an unbuilt shim package inconsistent with the
      real installable `amp_client` package. Needs a design decision
      (wire into the build or delete), unrelated to launch readiness but
      worth resolving before drawing outside attention to the SDK layout.

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

1. Decide how `LifecycleEngine.process_all()` gets scheduled in the
   reference server (item above). This is the biggest gap between what the
   marketing copy describes and what a fresh `docker compose up -d` does.
2. Decide the `sdk/python/amp/` shim's fate.
3. Kiel's own call on whether this project gets ongoing development or
   stays at its current, honestly-documented depth (see
   `projects/agent-memory-protocol.md` roadmap). That decision should
   land before any of this launch material actually gets published.
