"""The retention window: the rule, and the dates it is built from.

`spec/v0.1.0/lifecycle.md` §5 and RFC §5 make the server responsible for holding
a deleted cell for at least 30 days and for refusing a purge before then. The
enforcement itself is exercised against every backend in
`test_adapter_contract.py`; this module pins the arithmetic and the wording, since
an operator hitting the refusal is the intended reader of it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from conftest import make_cell

from amp_server.models import LifecycleStatus
from amp_server.retention import (
    RETENTION_DAYS,
    RetentionWindowError,
    deletion_time,
    enforce_retention_window,
    retention_days_remaining,
    retention_deadline,
    retention_elapsed,
    retention_remaining,
)

_NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)


def _deleted_cell(deleted_at: datetime):
    cell = make_cell(status=LifecycleStatus.ARCHIVED)
    cell.lifecycle.last_updated_at = deleted_at
    cell.lifecycle.status = LifecycleStatus.DELETED
    return cell


def test_the_floor_is_the_specs_thirty_days():
    assert RETENTION_DAYS == 30


def test_the_deletion_time_is_the_last_update():
    """`mark_deleted` stamps `last_updated_at`, and `deleted` is terminal."""
    cell = _deleted_cell(_NOW)
    assert deletion_time(cell) == _NOW


def test_a_naive_timestamp_is_read_as_utc():
    """A cell built by hand may have no timezone; it must not blow up."""
    cell = _deleted_cell(_NOW)
    cell.lifecycle.last_updated_at = _NOW.replace(tzinfo=None)
    assert deletion_time(cell) == _NOW


def test_the_deadline_is_thirty_days_after_deletion():
    cell = _deleted_cell(_NOW)
    assert retention_deadline(cell) == _NOW + timedelta(days=30)


def test_remaining_is_zero_once_the_window_has_passed():
    """Never negative: a cell deleted long ago has nothing left to wait for."""
    old = _deleted_cell(_NOW - timedelta(days=400))
    assert retention_remaining(old, now=_NOW) == timedelta(0)


def test_the_window_has_not_elapsed_one_second_early():
    cell = _deleted_cell(_NOW - timedelta(days=30) + timedelta(seconds=1))
    assert retention_elapsed(cell, now=_NOW) is False


def test_the_window_has_elapsed_at_the_deadline():
    cell = _deleted_cell(_NOW - timedelta(days=30))
    assert retention_elapsed(cell, now=_NOW) is True


def test_enforcing_refuses_inside_the_window_and_names_the_date():
    cell = _deleted_cell(_NOW - timedelta(days=3))

    with pytest.raises(RetentionWindowError) as raised:
        enforce_retention_window(cell, now=_NOW)

    message = str(raised.value)
    assert cell.id in message
    assert "2026-10-01" in message  # deleted on
    assert "2026-10-31" in message  # purgeable from
    assert "27 days remaining" in message
    assert "§5" in message


def test_enforcing_allows_past_the_window():
    cell = _deleted_cell(_NOW - timedelta(days=31))
    enforce_retention_window(cell, now=_NOW)  # does not raise


def test_a_longer_window_is_honoured_too():
    """The spec sets a floor, so an implementation may hold cells longer."""
    cell = _deleted_cell(_NOW - timedelta(days=40))

    with pytest.raises(RetentionWindowError, match="50 days remaining"):
        enforce_retention_window(cell, retention_days=90, now=_NOW)

    # The same cell satisfies the 30-day floor, because it is 10 days past it.
    enforce_retention_window(cell, retention_days=30, now=_NOW)


@pytest.mark.parametrize(
    ("days_deleted", "expected"),
    [
        (0, 30),  # rounded up: the deadline is 30 days away, not 29.99
        (1, 29),
        (3, 27),
        (29, 1),  # a partial day is still a day, never 0
        (30, 0),  # the deadline: nothing left to wait for
    ],
)
def test_days_remaining_is_rounded_up(days_deleted: int, expected: int):
    cell = _deleted_cell(_NOW - timedelta(days=days_deleted))
    assert retention_days_remaining(cell, now=_NOW) == expected
