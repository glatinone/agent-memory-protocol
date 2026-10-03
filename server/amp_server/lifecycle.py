"""LifecycleEngine — decay computation and status transitions."""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime

from amp_server.models import LifecycleStatus, MemoryCell, MemoryCellUpdate
from amp_server.storage.base import InvalidTransitionError, StorageAdapter

logger = logging.getLogger(__name__)

STALE_THRESHOLD = 0.3
ARCHIVE_STALE_DAYS = 30


def check_status_transition(current: LifecycleStatus, new: LifecycleStatus) -> None:
    """Refuse a status change the spec does not allow from a write (spec §2).

    The transition table permits a client to archive a cell (the DELETE flow
    archives first) and to bring a `stale` cell back to `active`. It forbids
    exactly two things, which is all this enforces:

    - an `archived` cell returning to `active` or `stale`;
    - reaching `deleted` by anything other than `DELETE /memories/{id}`.

    `deleted` is also terminal, so no further change is allowed from it.

    Raises InvalidTransitionError, which the API layer renders as
    `409 INVALID_TRANSITION`.
    """
    if new == current:
        return
    if new == LifecycleStatus.DELETED:
        raise InvalidTransitionError(
            "status cannot be set to 'deleted' directly; "
            "use DELETE /amp/v1/memories/{id}, which requires the cell to be archived"
        )
    if current == LifecycleStatus.DELETED:
        raise InvalidTransitionError(
            "'deleted' is terminal; the status of a deleted cell cannot be changed"
        )
    if current == LifecycleStatus.ARCHIVED:
        raise InvalidTransitionError(
            f"an archived cell cannot return to '{new.value}'; "
            "re-create the cell instead"
        )


def compute_decay_score(cell: MemoryCell, now: datetime | None = None) -> float:
    """Compute decay score: importance × confidence × e^(-decay_rate × Δt_days)."""
    if now is None:
        now = datetime.now(UTC)
    # Spec §7.1: use last_accessed_at if available, else created_at
    reference = cell.lifecycle.last_accessed_at or cell.lifecycle.created_at
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    delta_days = (now - reference).total_seconds() / 86400.0
    return (
        cell.scoring.importance
        * cell.scoring.confidence
        * math.exp(-cell.scoring.decay_rate * delta_days)
    )


class LifecycleEngine:
    def __init__(self, storage: StorageAdapter) -> None:
        self._storage = storage

    async def evaluate_cell(self, cell: MemoryCell) -> LifecycleStatus:
        """Determine what status a cell should have based on its decay score."""
        if cell.lifecycle.status == LifecycleStatus.DELETED:
            return LifecycleStatus.DELETED

        score = compute_decay_score(cell)
        now = datetime.now(UTC)

        if cell.lifecycle.status == LifecycleStatus.STALE:
            # Spec §2: a PATCH that raises the decay score back above threshold
            # returns the cell to `active` on the next engine run. A GET resets
            # `last_accessed_at`, which lifts the score the same way — so a
            # re-read cell comes back to `active` rather than staying stale
            # forever until it is archived.
            if score >= STALE_THRESHOLD:
                return LifecycleStatus.ACTIVE

            last_update = cell.lifecycle.last_updated_at or cell.lifecycle.created_at
            if last_update.tzinfo is None:
                last_update = last_update.replace(tzinfo=UTC)
            stale_days = (now - last_update).total_seconds() / 86400.0
            if stale_days >= ARCHIVE_STALE_DAYS:
                return LifecycleStatus.ARCHIVED

        if cell.lifecycle.status == LifecycleStatus.ACTIVE and score < STALE_THRESHOLD:
            return LifecycleStatus.STALE

        return cell.lifecycle.status

    async def process_all(self) -> dict[str, int]:
        """Run decay evaluation on all cells. Returns counts of transitions."""
        cells = await self._storage.list_all()
        transitions = {
            "active_to_stale": 0,
            "stale_to_archived": 0,
            "stale_to_active": 0,
        }

        for cell in cells:
            if cell.lifecycle.status in (
                LifecycleStatus.ARCHIVED,
                LifecycleStatus.DELETED,
            ):
                continue

            new_status = await self.evaluate_cell(cell)
            if new_status != cell.lifecycle.status:
                old_status = cell.lifecycle.status
                update = MemoryCellUpdate(
                    lifecycle=cell.lifecycle.model_copy(update={"status": new_status})
                )
                await self._storage.update(cell.id, update)
                key = f"{old_status.value}_to_{new_status.value}"
                transitions[key] = transitions.get(key, 0) + 1
                logger.info(
                    "Cell %s transitioned: %s → %s",
                    cell.id,
                    old_status.value,
                    new_status.value,
                )

        return transitions
