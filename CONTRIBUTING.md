# Contributing to AMP (Agent Memory Protocol)

Thank you for your interest in contributing to AMP. Contributions can target
either the protocol specification or the reference implementation:

- **Spec** (`spec/`) — the schema and normative behavior of the protocol
  (e.g. `spec/v0.1.0/memory-cell.schema.json`, `spec/v0.1.0/lifecycle.md`).
- **Reference server** (`server/`) — the FastAPI-based reference
  implementation (`amp_server`).
- **SDK** (`sdk/`) — the client library used by agents to talk to an AMP
  server.

## Before You Start

- For non-trivial changes (new endpoints, schema changes, behavioral
  changes to decay/lifecycle or access control), please open an issue first
  to discuss the approach before writing code.
- Check open issues and pull requests to avoid duplicate work.

## Making a Change

1. Fork the repository and create a branch for your change.
2. Keep **one logical change per pull request**. Do not mix, for example, a
   spec amendment with an unrelated server refactor, or multiple unrelated
   bug fixes in a single PR. Smaller, focused PRs are easier to review and
   merge.
3. If your change amends or clarifies existing behavior defined in the spec,
   reference the relevant section number/heading of the spec document being
   amended (e.g. "Amends `spec/v0.1.0/lifecycle.md` §3.2 — decay transition
   timing") in your PR description and, where useful, in code comments.
4. Follow the existing Python style used in the codebase you are touching
   (`server/` and `sdk/` are both standard Python packages configured via
   `pyproject.toml`). Match the conventions already present in the file you
   are editing rather than introducing a new style — this includes naming,
   typing, docstring conventions, and import ordering.
5. Add or update tests for any behavioral change. Untested behavioral
   changes are unlikely to be merged.

## Running Tests Locally

Tests are run with `pytest -v`, matching what CI does in
`.github/workflows/ci.yml`.

**Server:**
```bash
cd server
pip install -e ".[dev]"
pytest -v
```

**SDK:**
```bash
cd sdk
pip install -e ".[dev,langchain]"
pytest -v python/tests
```

Please run the relevant test suite locally before opening a pull request,
and make sure it passes. Pull requests that touch both `server/` and `sdk/`
should have both suites passing.

## Pull Request Requirements

Before requesting review, make sure your PR:

- [ ] Contains one logical change (spec amendment, bug fix, or feature —
      not a mix)
- [ ] Passes `pytest -v` for every package it touches (`server/`, `sdk/`)
- [ ] References the relevant spec section number if it amends existing
      spec behavior
- [ ] Follows the existing Python style of the surrounding code
- [ ] Includes or updates tests for any behavioral change
- [ ] Includes a clear description of *why* the change is needed, not just
      what changed

## Reporting Security Issues

Please do **not** open a public issue for security vulnerabilities. See
[SECURITY.md](SECURITY.md) for how to report them privately via GitHub
Security Advisories.

## Questions

If anything about contributing to the spec vs. the implementation is
unclear, open an issue and ask — we're happy to point you in the right
direction.
