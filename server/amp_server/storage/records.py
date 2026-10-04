"""Reading and writing a stored cell.

Two storage backends now hold the same objects, so the rules about how a cell is
serialized, rebuilt, and patched belong in one place. Duplicating them per
backend is how the read-access rule drifted apart in `storage/chroma.py` before
it was unified, so this module exists to make that structurally impossible for
the parts of the record lifecycle that are not backend-specific.

What lives here is what a backend must agree on:
- how a cell becomes JSON and comes back;
- which fields a partial update may never change;
- how a partial update merges into a stored cell.
"""

from __future__ import annotations

import json
from typing import Any

from amp_server.models import MemoryCell

# Fields a PATCH may never change, per `MemoryCellUpdate`'s own docstring.
IMMUTABLE_KEYS = frozenset({"id", "type", "amp_version", "identity"})


def serialize_cell(cell: MemoryCell) -> dict[str, Any]:
    """Convert a MemoryCell to a JSON-safe dict (all datetimes as ISO strings)."""
    return json.loads(cell.model_dump_json())


def deserialize_cell(data: dict[str, Any]) -> MemoryCell:
    """Reconstruct a MemoryCell from a stored dict."""
    return MemoryCell.model_validate(data)


def apply_updates(
    target: dict[str, Any], updates: dict[str, Any], _root: bool = True
) -> None:
    """Recursively merge `updates` into `target`, blocking immutable top-level keys."""
    for key, value in updates.items():
        if _root and key in IMMUTABLE_KEYS:
            continue
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            apply_updates(target[key], value, _root=False)
        else:
            target[key] = value
