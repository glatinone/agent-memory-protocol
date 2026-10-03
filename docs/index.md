# AMP - Agent Memory Protocol

**An open protocol for AI agent memory interoperability.**

Like MCP for tool calling - but for memory.

[![CI](https://github.com/glatinone/agent-memory-protocol/actions/workflows/ci.yml/badge.svg)](https://github.com/glatinone/agent-memory-protocol/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://github.com/glatinone/agent-memory-protocol/blob/master/LICENSE)

---

## What is AMP?

AMP (Agent Memory Protocol) is an open, HTTP-native protocol for storing, retrieving,
and sharing structured memory between AI agents across frameworks, vendors, and sessions.

Agents read and write a shared memory tier using a standardized **Memory Cell** schema.
AMP handles access control, semantic search, and decay-archival lifecycles out of the box.

## Why it exists

Most agent frameworks lock memory to a single session or a single vendor. AMP defines the
wire format and the lifecycle so memory can move between agents instead of dying with the
process that created it.

| Capability | AMP | Raw HTTP + vector DB | Framework memory | MCP |
|---|---|---|---|---|
| Open standard schema | Yes | No | No | No |
| Lifecycle and decay | Yes | No | No | No |
| Per-cell access policy | Yes | No | No | No |
| Cross-agent sharing | Yes | No | No | No |

## Start here

- [Getting Started](getting-started.md) - a server running and your first memory in five minutes
- [Protocol Specification](spec-explained.md) - Memory Cells, state transitions, decay math
- [API Reference](api-reference.md) - endpoints and payloads
- [FAQ](faq.md) - common questions, and what the reference server does *not* yet do

## Status

AMP is an early, honest reference implementation. The spec is `v0.1.0`, the SDK is not yet
on PyPI (install from source), and the decay engine runs on a background schedule by
default - the interval configurable, or the scheduler disabled for deployments that prefer
to drive it themselves. The SDK's distribution status and the scheduler's defaults are
tracked openly rather than glossed over.

## Get involved

- [Repository](https://github.com/glatinone/agent-memory-protocol)
- [Contributing guide](https://github.com/glatinone/agent-memory-protocol/blob/master/.github/CONTRIBUTING.md)
- [Security policy](https://github.com/glatinone/agent-memory-protocol/blob/master/SECURITY.md)
