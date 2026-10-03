# AMP Conformance Suite

A runnable definition of what it means to implement the Agent Memory Protocol.

The suite is two things: **test vectors** derived from the specification, and a
**runner** that executes them. It is deliberately independent of this project's
reference server - it imports nothing from `amp_server` and talks to a server
only over the wire - so it can be pointed at any implementation.

## Run it

Against the reference server in this repository:

```bash
cd server && pip install -e . && uvicorn amp_server.main:app --port 8765 &
pip install -e conformance/
amp-conformance --base-url http://127.0.0.1:8765
```

Against your own implementation:

```bash
pip install -e conformance/                       # or: pip install amp-conformance
amp-conformance --base-url https://memory.example.com
```

Local checks only, with no server involved:

```bash
amp-conformance
```

Write a machine-readable report with `--json report.json`, run one category with
`--only http_contract`, or point at a different schema with `--spec PATH`.

The exit code is `0` when nothing failed and `1` otherwise, so it drops straight
into CI.

## What is checked

| Category | Needs a server | Checks |
|---|---|---|
| `schema` | no | Standalone `MemoryCell` documents against `spec/v0.1.0/memory-cell.schema.json`, both documents that must validate and documents that must not. |
| `decay` | no | `decay_score = importance x confidence x e^(-decay_rate x delta_days)` recomputed from `spec/v0.1.0/lifecycle.md`, including the stale threshold at `0.3` and the half-life. |
| `http_contract` | yes | Status codes and error bodies: a missing agent identity is `401`, an unknown cell is `403` and never `404`, only an archived cell can be deleted, an archived cell cannot return to `active`, and a write cannot reach `deleted`. |
| `access_control` | yes | The read and write decision for every agent in a policy matrix, checked through three surfaces at once: `GET` (read), `PATCH` (write) and `POST /memories/search` (read through the ranking path). |

The `access_control` category is the one that catches a server applying one rule
to a by-id read and a different one to search - a real divergence this repository
shipped until the suite was written.

## Known gaps

A vector may carry `"known_gap": "reason"`. Such a case is reported separately
instead of counting as a failure, which lets the suite land before an
implementation catches up. The mechanism cannot rot: a case that *passes* while
still marked a gap is reported as `unexpected_pass` and is meant to be promoted
to a plain vector.

`0 known gaps` in the summary means the reference server conforms to every
vector in the suite.

## Adding a vector

Edit the relevant file in `amp_conformance/vectors/` and re-run. Write vectors
from the specification, not from the reference implementation - a vector copied
out of the code can only ever confirm the code.

For `http_contract`, each step is `{"request": ..., "expect": ...}`. A step may
`"capture": "name"` its response body, and later steps can refer to it as
`{name.dotted.path}` anywhere in the request. Assertions are `status`,
`error_code`, `has_fields`, `id_prefix` and `json_equals` (dotted paths).
