"""Access control — permission checker for AMP memory cells."""

from __future__ import annotations

import fnmatch

from amp_server.models import MemoryCell


class AccessDeniedError(Exception):
    """Raised when an agent lacks permission to access a memory cell."""

    def __init__(self, agent_id: str, memory_id: str, action: str) -> None:
        self.agent_id = agent_id
        self.memory_id = memory_id
        self.action = action
        super().__init__(
            f"Agent '{agent_id}' is not allowed to {action} memory '{memory_id}'"
        )


def _matches_any(agent_id: str, patterns: list[str]) -> bool:
    """Check if agent_id matches any of the wildcard patterns."""
    return any(fnmatch.fnmatch(agent_id, pattern) for pattern in patterns)


def check_read_access(cell: MemoryCell, agent_id: str) -> bool:
    """Return True if the agent can read this cell."""
    if cell.access_policy.public:
        return True
    if agent_id == cell.identity.created_by:
        return True
    if agent_id == cell.identity.owner_id:
        return True
    if cell.access_policy.readable_by and _matches_any(
        agent_id, cell.access_policy.readable_by
    ):
        return True
    if not cell.access_policy.readable_by and not cell.access_policy.writable_by:
        return agent_id in (cell.identity.owner_id, cell.identity.created_by)
    return False


def check_write_access(cell: MemoryCell, agent_id: str) -> bool:
    """Return True if the agent can write/modify this cell."""
    if agent_id == cell.identity.created_by:
        return True
    if agent_id == cell.identity.owner_id:
        return True
    if cell.access_policy.writable_by and _matches_any(
        agent_id, cell.access_policy.writable_by
    ):
        return True
    if not cell.access_policy.writable_by:
        return agent_id in (cell.identity.owner_id, cell.identity.created_by)
    return False


def enforce_read(cell: MemoryCell, agent_id: str) -> None:
    """Raise AccessDeniedError if the agent cannot read this cell."""
    if not check_read_access(cell, agent_id):
        raise AccessDeniedError(agent_id, cell.id, "read")


def enforce_write(cell: MemoryCell, agent_id: str) -> None:
    """Raise AccessDeniedError if the agent cannot write this cell."""
    if not check_write_access(cell, agent_id):
        raise AccessDeniedError(agent_id, cell.id, "write")
