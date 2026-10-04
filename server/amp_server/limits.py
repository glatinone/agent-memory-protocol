"""The server limits that `GET /spec` advertises, enforced in one place.

`/spec` tells a client the largest cell this server accepts. Advertising a limit
that nothing enforces is a claim with no behaviour behind it: a client that sizes
its payloads against the advertised number would still be allowed to store
something far larger.

So the number lives here, `/spec` reports it, and the create and update paths
measure against it. A conformance check verifies the server honours its own
advertised value rather than a fixed one, which keeps this honest for any
implementation.
"""

from __future__ import annotations

from amp_server.errors import AMPError
from amp_server.models import MemoryCell

# 64 KiB measured on the serialized cell, i.e. the document a client gets back.
MAX_CELL_SIZE_BYTES = 65536


def cell_size_bytes(cell: MemoryCell) -> int:
    """Size of the cell as the API serializes it."""
    return len(cell.model_dump_json().encode("utf-8"))


def enforce_cell_size(cell: MemoryCell) -> None:
    """Refuse a cell larger than the advertised maximum.

    Raises AMPError, which the API layer renders as
    `413 CELL_TOO_LARGE`. The error envelope is the same one every other
    protocol error uses.
    """
    size = cell_size_bytes(cell)
    if size > MAX_CELL_SIZE_BYTES:
        raise AMPError(
            413,
            "CELL_TOO_LARGE",
            f"the serialized cell is {size} bytes, above the advertised "
            f"maximum of {MAX_CELL_SIZE_BYTES}",
        )
