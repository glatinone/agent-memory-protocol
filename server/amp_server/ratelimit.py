"""A per-cell budget on rewriting `scoring` (RFC-AMP-001 §5).

The RFC names decay-score manipulation as a threat: a caller PATCHing `scoring`
in a loop can hold a cell `active` past its relevance window, or drive a competing
memory into archive. Its first mitigation is structural and already in place - a
scoring PATCH only takes effect on the next `LifecycleEngine.process_all`, so the
engine's cadence bounds how fast manipulation can land. Its second is this, asking
implementations to rate-limit scoring PATCH frequency per cell. Nothing did.

Two choices worth stating:

- **Only a PATCH carrying `scoring` is counted.** Rewriting text, metadata or the
  access policy is not what the threat describes, and counting those would refuse
  ordinary edits to cover an attack they have nothing to do with.
- **A refused attempt is not recorded.** Counting refusals would let a caller
  extend its own lockout by hammering, and would make `Retry-After` grow while the
  caller waits. Not recording means the wait shrinks as the oldest allowed edit
  ages out, which is the behaviour the number promises.

The counters live in this process. Two server processes over one Postgres keep two
budgets - worth knowing, and better than a shared counter that would need its own
storage and its own consistency story. The threat is one caller in a loop, and one
process sees that caller's whole stream.
"""

from __future__ import annotations

import logging
import math
import os
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from amp_server.models import MemoryCellUpdate

logger = logging.getLogger(__name__)

#: Scoring edits allowed per cell per window, when nothing else is configured.
#: Five is generous for a person re-scoring a memory and useless for a loop; the
#: lifecycle engine runs hourly by default, so this is five edits per cycle.
DEFAULT_MAX_PATCHES = 5
DEFAULT_WINDOW_SECONDS = 3600

#: How many cells are tracked at once. Counters for cells nobody edits are
#: dropped as their window empties; this caps the rest.
DEFAULT_MAX_TRACKED_CELLS = 10_000


@dataclass(frozen=True)
class ScoringPatchLimit:
    """How often one cell's `scoring` may be rewritten.

    `max_patches` of 0 disables the limit, which is the honest way to express
    "this deployment does not want it" rather than a very large number that
    reads like a policy.
    """

    max_patches: int = DEFAULT_MAX_PATCHES
    window_seconds: int = DEFAULT_WINDOW_SECONDS

    @property
    def enabled(self) -> bool:
        return self.max_patches > 0 and self.window_seconds > 0

    def to_json(self) -> dict[str, Any] | None:
        """What `GET /spec` reports, or None when the limit is off."""
        if not self.enabled:
            return None
        return {
            "max_patches": self.max_patches,
            "window_seconds": self.window_seconds,
        }


def limit_from_env() -> ScoringPatchLimit:
    """Read the limit from the environment, falling back rather than failing.

    A misread number here degrades a mitigation, it does not corrupt data, so
    this warns and uses the default instead of stopping the server - unlike the
    embedding provider and the key store, where a wrong value is worse than no
    server at all.
    """
    return ScoringPatchLimit(
        max_patches=_int_env("AMP_SCORING_PATCH_LIMIT", DEFAULT_MAX_PATCHES),
        window_seconds=_int_env(
            "AMP_SCORING_PATCH_WINDOW_SECONDS", DEFAULT_WINDOW_SECONDS
        ),
    )


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("%s=%r is not an integer; using %d", name, raw, default)
        return default
    if value < 0:
        logger.warning("%s must not be negative; using %d", name, default)
        return default
    return value


class ScoringPatchLimiter:
    """Counts scoring edits per cell, in memory, over a sliding window."""

    def __init__(
        self,
        limit: ScoringPatchLimit,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_tracked_cells: int = DEFAULT_MAX_TRACKED_CELLS,
    ) -> None:
        self.limit = limit
        self._clock = clock
        self._max_tracked = max_tracked_cells
        self._seen: OrderedDict[str, deque[float]] = OrderedDict()

    def check_and_record(self, cell_id: str) -> int:
        """Count one attempt and return the seconds to wait; 0 when allowed.

        One call rather than `check` plus `record`, so a caller cannot pass the
        check and forget to spend the budget.
        """
        if not self.limit.enabled:
            return 0

        now = self._clock()
        stamps = self._seen.get(cell_id)
        if stamps is None:
            stamps = deque()
            self._seen[cell_id] = stamps
        else:
            self._seen.move_to_end(cell_id)
            self._prune(stamps, now)

        if len(stamps) >= self.limit.max_patches:
            return max(1, math.ceil(self.limit.window_seconds - (now - stamps[0])))

        stamps.append(now)
        self._evict_if_crowded()
        return 0

    def forget(self, cell_id: str) -> None:
        """Drop a cell's counters, e.g. once it has been purged."""
        self._seen.pop(cell_id, None)

    def tracked_cells(self) -> int:
        """How many cells are being counted, for tests and diagnostics."""
        return len(self._seen)

    def _prune(self, stamps: deque[float], now: float) -> None:
        while stamps and now - stamps[0] >= self.limit.window_seconds:
            stamps.popleft()

    def _evict_if_crowded(self) -> None:
        """Forget the least recently touched cells once the cap is reached.

        Bounded memory matters more than perfect accounting for cells that were
        edited once, long ago: evicting the oldest entry can only ever make the
        limit more permissive, never refuse an edit that should be allowed.
        """
        while len(self._seen) > self._max_tracked:
            self._seen.popitem(last=False)


def patch_touches_scoring(body: MemoryCellUpdate) -> bool:
    """Whether this PATCH actually rewrites `scoring`.

    `{"scoring": null}` sends nothing to change, so it costs nothing: the budget
    is spent by writes, not by requests.
    """
    return body.scoring is not None
