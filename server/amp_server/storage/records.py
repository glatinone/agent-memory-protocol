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

#: Key paths a partial update may never change, per `MemoryCellUpdate`'s own
#: docstring and `docs/api-reference.md`.
#:
#: Paths rather than top-level names, because the rule is about a field and not
#: its depth: `lifecycle.created_at` is the anchor the decay formula measures a
#: cell's age from, so an update able to rewrite it could reset that age and
#: defeat the decay the whole lifecycle is built on. The update model omits the
#: field, and this is the same rule for the raw dict path the server uses
#: internally, where no model sees the update.
IMMUTABLE_PATHS = frozenset(
    {
        ("id",),
        ("type",),
        ("amp_version",),
        ("identity",),
        ("lifecycle", "created_at"),
    }
)


def serialize_cell(cell: MemoryCell) -> dict[str, Any]:
    """Convert a MemoryCell to a JSON-safe dict (all datetimes as ISO strings)."""
    return json.loads(cell.model_dump_json())


def deserialize_cell(data: dict[str, Any]) -> MemoryCell:
    """Reconstruct a MemoryCell from a stored dict."""
    return MemoryCell.model_validate(data)


def apply_updates(
    target: dict[str, Any], updates: dict[str, Any], _path: tuple[str, ...] = ()
) -> None:
    """Recursively merge `updates` into `target`, skipping immutable key paths."""
    for key, value in updates.items():
        if (*_path, key) in IMMUTABLE_PATHS:
            continue
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            apply_updates(target[key], value, _path=(*_path, key))
        else:
            target[key] = value
