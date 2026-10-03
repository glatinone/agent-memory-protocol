# Contributing to AMP

Thank you for your interest in contributing to AMP. Contributions can target
either the protocol specification or the reference implementation:

- **Spec** (`spec/`) - the schema and normative behavior of the protocol
  (e.g. `spec/v0.1.0/memory-cell.schema.json`, `spec/v0.1.0/lifecycle.md`).
- **Reference server** (`server/`) - the FastAPI-based reference
  implementation (`amp_server`).
- **SDK** (`sdk/`) - the client library used by agents to talk to an AMP
  server.

---

## Before You Start

- For non-trivial changes (new endpoints, schema changes, behavioral changes to
  decay/lifecycle or access control), open an issue first to discuss the
  approach before writing code.
- Check open issues and pull requests to avoid duplicate work.

---

## Setting Up Your Development Environment

The reference server needs Python 3.11+; the Python SDK needs 3.10+.

```bash
git clone https://github.com/glatinone/agent-memory-protocol.git
cd agent-memory-protocol

# Optional but recommended
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Reference server (ruff and mypy come in through the dev extra)
cd server && pip install -e ".[dev]"

# Python SDK, if you are working on the client
cd ../sdk && pip install -e ".[dev,langchain]"
```

The Node SDK under `sdk/node/` has no dependencies at all (Node 18+ ships
`fetch`) and no build step, so there is nothing to install for it.

---

## Running Tests

Tests run with `pytest`, matching what CI does in `.github/workflows/ci.yml`.

```bash
# Reference server, from server/
pytest -v

# A single file, from server/
pytest tests/test_memory_crud.py -v

# Python SDK, from sdk/
pytest -v python/tests

# Node SDK, from sdk/node/ (runs against a live server when one is reachable)
node --test test/client.test.js
```

---

## Quality Gates

CI runs lint, format and type checks for both Python packages, and a pull
request that fails any of them will not be merged. Run the same gates locally
before pushing:

```bash
# from server/, and again from sdk/
ruff check .
ruff format --check .
mypy
```

Both packages configure ruff and mypy in their own `pyproject.toml`. Ruff
resolves configuration per file, so running it from the repository root covers
both packages correctly.

`pre-commit` is optional, and runs the same lint and format hooks before each
commit so a failure surfaces locally instead of in CI:

```bash
pip install pre-commit
pre-commit install
```

---

## Making a Change

1. Fork the repository and create a branch for your change.
2. Keep **one logical change per pull request**. Do not mix, for example, a spec
   amendment with an unrelated server refactor, or multiple unrelated bug fixes
   in a single PR. Smaller, focused PRs are easier to review and merge.
3. If your change amends or clarifies behavior defined in the spec, reference
   the relevant section number or heading in your PR description and, where
   useful, in code comments (e.g. "Amends `spec/v0.1.0/lifecycle.md` §3.2 -
   decay transition timing").
4. Follow the existing Python style of the code you are touching - naming,
   typing, docstring conventions and import ordering. Ruff enforces the
   mechanical parts; match the surrounding code for the rest.
5. Add or update tests for any behavioral change. Untested behavioral changes
   are unlikely to be merged.
6. Link related issues in the PR description (`Closes #123`).

---

## Code Style & Standards

- **Formatting and linting:** Ruff, configured per package. `ruff format` is
  the formatter of record.
- **Type hints:** Required for new functions, methods and classes; mypy checks
  both packages in CI.
- **Tests:** Every *behavior* needs a test, not every line. Two conventions the
  suites rely on: a behavior claimed in the README or docs should have a test
  or a live verification behind it, and docstrings explain *why* rather than
  restating *what* the code does.

---

## RFC Process (Protocol Spec Changes)

If you want to propose a protocol specification change or addition, submit an
RFC first:

1. Add a markdown file under `spec/rfcs/` describing the proposed change (see
   `spec/rfcs/RFC-AMP-001.md` for the shape this takes).
2. Open a pull request referencing the RFC.
3. Once the RFC is reviewed, discussed and merged, the corresponding
   implementation can proceed.

---

## Reporting Security Issues

Please do **not** open a public issue for security vulnerabilities. See
[SECURITY.md](../SECURITY.md) for how to report them privately via GitHub
Security Advisories.
