"""The specification is normative; the code must not drift away from it.

`MemoryCell.model_config` carries an example that pydantic publishes in the
OpenAPI document, so it is what `/docs` and every generated client show. That
example used to carry an id without the `mem_` prefix, which the protocol's own
schema forbids (`^mem_[0-9A-Z]{26}$`), so the documented example was not a valid
AMP document. The conformance suite under `conformance/` validates the same
schema; this catches the drift from inside the server suite.
"""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft7Validator

from amp_server.models import MemoryCell

SPEC_PATH = (
    Path(__file__).resolve().parents[2] / "spec" / "v0.1.0" / "memory-cell.schema.json"
)


def _spec_schema() -> dict:
    with SPEC_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def test_the_openapi_example_is_a_valid_amp_document():
    validator = Draft7Validator(_spec_schema())
    example = MemoryCell.model_config["json_schema_extra"]["example"]

    errors = sorted(validator.iter_errors(example), key=lambda e: list(e.path))
    assert not errors, "; ".join(f"{list(e.path)}: {e.message}" for e in errors)


def test_the_spec_schema_is_reachable_from_the_server_tests():
    """If this moves, the check above would silently stop testing anything."""
    assert SPEC_PATH.is_file(), f"spec schema not found at {SPEC_PATH}"
