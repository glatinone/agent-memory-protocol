"""Optional API-key authentication for the HTTP binding.

`spec/rfcs/RFC-AMP-001.md` §6.1 carries agent identity in the `X-AMP-Agent-ID`
header and defines no credential, so today a client can claim to be any agent it
likes: the header is an assertion, not proof. Every access rule downstream -
`readable_by`, `writable_by`, the owner check - is decided from that assertion.

This module adds proof without changing the binding. The agent id keeps
travelling in the header exactly where the spec puts it; when a key store is
configured, the caller must additionally present a key that belongs to that id.

It is off unless `AMP_API_KEYS_FILE` is set. A reference server must stay usable
with no configuration, and the spec's binding must keep working as written - but
a deployment that has configured keys and then finds them unreadable must not
quietly fall back to trusting the header, so a broken store stops the server.

Two deliberate choices:

- **Hashes, not keys.** The file stores `sha256:` digests, so a leaked file does
  not hand over working credentials. `python -m amp_server.auth hash <key>`
  prints the line to paste.
- **One 401 for every failure.** A wrong key and a key for an agent that does not
  exist answer identically, so the endpoint cannot be used to enumerate agent
  ids. The same reasoning as the uniform 403 on deleted cells in spec §8.4.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

SHA256_PREFIX = "sha256:"
ENV_VAR = "AMP_API_KEYS_FILE"


def digest(api_key: str) -> str:
    """The stored form of a key. Never the key itself."""
    return SHA256_PREFIX + hashlib.sha256(api_key.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ApiKeyStore:
    """Which key belongs to which agent id.

    One key per agent id rather than several: the store answers "is this key
    this agent's?", and a list of keys per agent would only widen what a leaked
    file is worth.
    """

    digests: Mapping[str, str]

    def verify(self, agent_id: str, presented_key: str) -> bool:
        """True when `presented_key` is the key registered for `agent_id`.

        Compared with `hmac.compare_digest` so the check does not reveal how much
        of a wrong key was right. An unknown agent id is compared against a
        throwaway digest rather than returning early, so a wrong-key attempt
        costs the same whether or not the agent exists.
        """
        expected = self.digests.get(agent_id, digest("no-such-agent"))
        return hmac.compare_digest(expected, digest(presented_key))

    def __len__(self) -> int:
        return len(self.digests)


def load_store(path: str | Path) -> ApiKeyStore:
    """Read a key store, refusing anything that is not a clean mapping.

    Raises ValueError naming the file and the offending entry. A store that is
    half-readable is worse than none: the entries that parsed would be enforced
    and the others silently would not.
    """
    store_path = Path(path)
    try:
        raw = json.loads(store_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(
            f"{ENV_VAR} points at {store_path}, which does not exist"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{store_path} is not valid JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError(
            f"{store_path} must be a JSON object mapping agent id to key digest"
        )

    digests: dict[str, str] = {}
    for agent_id, value in raw.items():
        if not isinstance(agent_id, str) or not agent_id:
            raise ValueError(f"{store_path} has an empty or non-string agent id")
        if not isinstance(value, str) or not value.startswith(SHA256_PREFIX):
            raise ValueError(
                f"{store_path}: entry {agent_id!r} must be a "
                f"'{SHA256_PREFIX}<hex>' digest, not a raw key"
            )
        if len(value) != len(SHA256_PREFIX) + 64:
            raise ValueError(f"{store_path}: entry {agent_id!r} is not a sha256 digest")
        digests[agent_id] = value

    if not digests:
        raise ValueError(
            f"{store_path} contains no agents, which would authenticate nobody; "
            f"unset {ENV_VAR} to run without keys"
        )
    return ApiKeyStore(digests=digests)


def store_from_env() -> ApiKeyStore | None:
    """The configured store, or None when this deployment has no keys.

    Called from the lifespan, so a malformed file stops startup instead of
    surfacing as a 401 on a request an operator expected to work.
    """
    path = os.environ.get(ENV_VAR)
    if not path:
        return None
    store = load_store(path)
    logger.info("API key authentication enabled for %d agent(s)", len(store))
    return store


def _main(argv: list[str]) -> int:
    """`python -m amp_server.auth hash <key>`: the value to put in the store.

    Prints the digest alone, because the agent id is the key in the store file
    and only the operator knows which id the key belongs to.
    """
    if len(argv) != 2 or argv[0] != "hash":
        print("usage: python -m amp_server.auth hash <api-key>")
        print("writes the sha256 value to use in the file named by AMP_API_KEYS_FILE")
        return 2
    print(digest(argv[1]))
    return 0


if __name__ == "__main__":  # pragma: no cover - operator convenience
    import sys

    raise SystemExit(_main(sys.argv[1:]))
