# AMP Launch Checklist

This checklist verifies that the Agent Memory Protocol (AMP) repository and associated tools are fully prepared for open source release.

## 1. Documentation & Specification
- [x] Top-level `README.md` complete and landing-page ready (T1)
- [x] Badges configured: PyPI version, build status, license
- [x] Mermaid architecture diagram verified
- [x] Protocol specification (`SPEC.md`) complete
- [x] MkDocs site configuration (`docs/mkdocs.yml`) set up (T2)
- [x] `getting-started.md` updated and placeholders removed
- [x] `faq.md` updated with released Python SDK details
- [x] `spec-explained.md` written explaining MemoryCells, state transitions, decay score math, and access policies

## 2. Code Implementations
- [x] Reference server (`server/`) complete with FastAPI and ChromaDB integration
- [x] All server tests pass (`pytest tests/ -v` showing 49 tests passing)
- [x] Python SDK client (`sdk/`) complete with sync, async, and LangChain support
- [x] Multi-agent demo (`examples/multi-agent-demo/`) implemented and run successfully
- [x] Local directories mapped for persistence via `AMP_PERSIST_DIR`

## 3. Launch Marketing Material
- [x] dev.to launch blog post written (`docs/blog/launch-post.md`) (T3)
- [x] Live multi-agent console run output embedded as verification log
- [x] "Show HN" submission text ready (`docs/hn-submission.md`)
- [x] recommended dev.to tags mapped (`docs/devto-tags.md`)

## 4. Community & Contribution Assets
- [x] GitHub bug report template created (`.github/ISSUE_TEMPLATE/bug_report.md`) (T4)
- [x] GitHub feature request template created (`.github/ISSUE_TEMPLATE/feature_request.md`)
- [x] GitHub RFC template created (`.github/ISSUE_TEMPLATE/rfc.md`)
- [x] Contribution guide created (`.github/CONTRIBUTING.md`) covering dev environment setup, pytest verification, type hinting, and spec RFC changes
- [x] Pull Request template configured (`.github/PULL_REQUEST_TEMPLATE.md`)
- [x] MIT `LICENSE` file present at the root

## 5. Build Verification
- [x] Verify no syntax errors in any project Python files (run `python -m py_compile`)
- [x] No broken internal markdown links in `README.md`
