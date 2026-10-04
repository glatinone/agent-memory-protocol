"""The deletion retention window, in one place.

`spec/v0.1.0/lifecycle.md` §5 and `spec/rfcs/RFC-AMP-001.md` §5 put retention on
the server: a deleted cell MUST be retained for at least 30 days, `purge` is
preconditioned on that window having elapsed, and "retention enforcement is the
responsibility of the server implementation, not the protocol client".

The rule used to live in a docstring asking the *caller* to wait. Nothing
enforced it, so `purge()` would destroy a cell one second after `DELETE` - which
is exactly the retention-window bypass the RFC lists as a threat, and it leaves
audit evidence unrecoverable in a window that exists for that purpose.

Keeping it in one module is the same decision made for `amp_server.ranking`, the
record rules and the access rule: a rule that two backends each reimplement is a
rule that drifts. This module imports nothing from the storage package, so every
adapter can use it without an import cycle.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from amp_server.models import MemoryCell

#: The spec's floor. An implementation may hold cells longer, never less.
RETENTION_DAYS = 30


class RetentionWindowError(Exception):
    """Raised when a purge is attempted inside the retention window."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def deletion_time(cell: MemoryCell) -> datetime:
    """When the cell was deleted.

    A deleted cell is terminal through the API, and `mark_deleted` stamps
    `last_updated_at` with the moment of the DELETE, so that field is the
    deletion time. `created_at` is only the fallback for a cell assembled by hand
    with no timestamps at all.
    """
    stamped = cell.lifecycle.last_updated_at or cell.lifecycle.created_at
    if stamped.tzinfo is None:
        return stamped.replace(tzinfo=UTC)
    return stamped


def retention_deadline(
    cell: MemoryCell, retention_days: int = RETENTION_DAYS
) -> datetime:
    """The first moment the cell may be purged."""
    return deletion_time(cell) + timedelta(days=retention_days)


def retention_remaining(
    cell: MemoryCell,
    retention_days: int = RETENTION_DAYS,
    now: datetime | None = None,
) -> timedelta:
    """How long is left before the cell may be purged. Never negative."""
    if now is None:
        now = datetime.now(UTC)
    remaining = retention_deadline(cell, retention_days) - now
    return remaining if remaining > timedelta(0) else timedelta(0)


def retention_elapsed(
    cell: MemoryCell,
    retention_days: int = RETENTION_DAYS,
    now: datetime | None = None,
) -> bool:
    """True once the window has passed and the cell may be purged.

    True at exactly the deadline: the window has then elapsed.
    """
    if now is None:
        now = datetime.now(UTC)
    return now >= retention_deadline(cell, retention_days)


def retention_days_remaining(
    cell: MemoryCell,
    retention_days: int = RETENTION_DAYS,
    now: datetime | None = None,
) -> int:
    """Whole days left, rounded up.

    Rounded up, not truncated: the number describes the deadline, and a fresh
    deletion with 29.99 days left is "30 days", not "29 days". It also keeps the
    last partial day from reading as "0 days remaining", which looks like the
    purge should already have been allowed.
    """
    remaining = retention_remaining(cell, retention_days, now)
    return math.ceil(remaining.total_seconds() / 86400)


def enforce_retention_window(
    cell: MemoryCell,
    retention_days: int = RETENTION_DAYS,
    now: datetime | None = None,
) -> None:
    """Refuse a purge that lands inside the retention window.

    The message names the date the cell becomes purgeable: an operator who hits
    this wants to know when to come back, not only that they were early.
    """
    if retention_elapsed(cell, retention_days, now):
        return
    if now is None:
        now = datetime.now(UTC)
    deadline = retention_deadline(cell, retention_days)
    days = retention_days_remaining(cell, retention_days, now)
    day_word = "day" if days == 1 else "days"
    raise RetentionWindowError(
        f"cell {cell.id} was deleted on {deletion_time(cell):%Y-%m-%d} and is "
        f"retained until {deadline:%Y-%m-%d} ({days} {day_word} remaining); "
        "spec lifecycle.md §5 requires this window to elapse before purge"
    )
