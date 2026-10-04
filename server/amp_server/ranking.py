"""How search results are ordered.

`spec/v0.1.0/lifecycle.md` §7 makes the decay score the protocol's stated
differentiator, so a search result has to reflect it. The rule is one blend of
vector similarity and decay, and it belongs in exactly one place: two backends
that each implement their own ranking would return different orders for the same
data, which is the class of divergence this repository already had to fix once
for access control.
"""

from __future__ import annotations

from amp_server.models import MemoryCell

# How much weight vector similarity takes versus the cell's current decay score
# (spec §7 - importance x confidence x e^(-decay_rate x delta_t)). Similarity
# still dominates: a barely-related but fresh cell must not outrank a highly
# relevant one. At similar relevance, the fresher/more important cell wins.
SIMILARITY_WEIGHT = 0.7
DECAY_WEIGHT = 0.3


def combined_score(similarity: float, cell: MemoryCell) -> float:
    """Blend vector similarity with decay into one ranking number."""
    # Deferred import: amp_server.lifecycle imports amp_server.storage.base, and
    # importing that package's base module imports the storage package, which
    # imports the adapters - a module-level import here would be circular.
    from amp_server.lifecycle import compute_decay_score

    decay = compute_decay_score(cell)
    return SIMILARITY_WEIGHT * max(0.0, similarity) + DECAY_WEIGHT * decay
