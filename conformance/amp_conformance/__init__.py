"""Conformance suite for the Agent Memory Protocol.

Two kinds of check live here:

- Local checks (schema, decay) need no server. They verify documents and
  arithmetic against the protocol specification itself.
- HTTP checks (contract, access) run against a live server given `--base-url`,
  and use only the wire protocol, so any implementation can be measured the
  same way.
"""

__version__ = "0.1.0"
