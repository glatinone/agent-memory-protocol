---
title: "AMP: an open protocol for AI agent memory, like MCP but for memory"
published: false
description: "MCP standardized how agents call tools. Nothing standardized how they remember. AMP is an open, HTTP-native protocol for storing, recalling, and sharing agent memory across frameworks."
tags: ai, python, opensource, webdev
cover_image:
---

Anthropic's Model Context Protocol gave agents a standard way to call tools. It left a different gap open: how do agents **remember**? Store, recall, and share context across frameworks, sessions, and vendors.

I built **AMP (Agent Memory Protocol)** to answer that. It's an open, HTTP-native protocol for agent memory interoperability.

- Repo: https://github.com/glatinone/agent-memory-protocol
- Docs: https://glatinone.github.io/agent-memory-protocol/
- Spec: https://github.com/glatinone/agent-memory-protocol/tree/master/spec/v0.1.0

## The problem: memory is fragmented

Every framework handles memory its own way. LangChain has its own memory classes. LlamaIndex has its own. CrewAI and AutoGen too. Managed memory services each have a proprietary data model.

So when you want a LangChain agent and a LlamaIndex agent to share context, you write a custom sync layer. When a session ends, the agent's context is either gone or buried somewhere other agents can't reach it. And there's no agreement on what a "memory" even contains, so there is nothing to sync in the first place.

## What existing options don't cover

- **Raw vector databases** store and search documents, but they have no concept of who an agent is, when a memory should fade, or who is allowed to read it.
- **Managed memory APIs** give you those things, but they lock your agent's state behind one vendor's API.
- **Framework memory classes** are locked to that framework by definition.

None of these is a protocol. What's missing is an interface any agent, in any language, can speak.

## What AMP defines

AMP decouples agent execution from memory storage. Three pieces:

**1. A Memory Cell schema.** One JSON shape for a memory: content, metadata, identity (owner, creator, session), scoring (importance, confidence, decay rate), access policy, and provenance.

**2. An HTTP-native API.** Plain REST under `/amp/v1`. Writing a memory is a POST with a JSON body. Access control is declared per cell and enforced by the `X-AMP-Agent-ID` header. Any language that can make an HTTP request can speak AMP, no SDK required.

**3. A lifecycle and decay engine.** Every cell has an importance score that decays over time. The reference server runs a background job that moves cells through `active` -> `stale` -> `archived` based on that score, so context that's no longer relevant drops out of search on its own. It runs by default, the interval is configurable, and you can disable it and trigger runs yourself through an admin endpoint.

## Access control is the part I care about most

Multi-agent systems need memory sharing, and sharing needs permission. AMP puts an `access_policy` on every cell:

```json
{
  "access_policy": {
    "readable_by": ["agent_billing_*"],
    "writable_by": ["agent_customer_service"],
    "public": false
  }
}
```

Wildcards work. `public` defaults to false. And a cell that has been deleted returns the same `403` whether it exists or not, so you can't probe for existence through error codes.

## See it work

The repo has a multi-agent demo where two agents share memory and a third is blocked:

```text
[AGENT A]
CustomerServiceAgent received: 'User prefers email correspondence.'
Stored preference memory ID: mem_01M405R0HS566J9DZDRESG4HV2

[AGENT B]
BillingAgent assisted user: user_123
Retrieved response: "I see you prefer email, so I will send your bill there."

[AGENT C]
MarketingAgent try_access results: 0 memories retrieved
Agent C retrieved 0 memories - access control working correctly

[SUMMARY]
AMP Demo complete. Two agents shared memory. One was blocked.
```

Agent B could read the preference because the policy allowed it. Agent C could not, and got nothing back.

## Using it

Start the server:

```bash
git clone https://github.com/glatinone/agent-memory-protocol.git
cd agent-memory-protocol/server
docker compose up -d
```

Then talk to it. Python:

```python
from amp_client import AMPClient

client = AMPClient("http://localhost:8765", agent_id="settings-agent")

cell = client.remember(
    content={"text": "User prefers dark mode for UI components"},
    owner_id="user-123",
    readable_by=["settings-agent", "ui-agent"],
)

ui_client = AMPClient("http://localhost:8765", agent_id="ui-agent")
results = ui_client.recall(
    query="what color scheme does the user prefer?",
    owner_id="user-123",
)
for item in results:
    print(item["content"]["text"])
```

Or in plain HTTP, no SDK at all:

```bash
curl -X POST http://localhost:8765/amp/v1/memories \
  -H "X-AMP-Agent-ID: my-agent" \
  -H "Content-Type: application/json" \
  -d '{"type":"semantic","content":{"text":"User prefers email"},"identity":{"owner_id":"user-123","owner_type":"user"}}'
```

There's a Node.js client too, with no dependencies (Node 18+ has `fetch`).

## What AMP is not, yet

Being straight about this, because it matters more than a feature list:

- **Not on PyPI or npm yet.** Install from the repo.
- **No hosted service.** You self-host. That's on purpose for now: your memory data stays yours while the protocol gets validated.
- **Python and Node.js clients only.** Go and Rust are planned.
- **ChromaDB is the only storage backend** wired up.
- **No auth on the memory endpoints.** Access control is per cell via the header, which suits local and single-tenant deployments, not an internet-facing server.

## What's next

More SDKs (Go, Rust), framework plugins beyond the existing LangChain integration, a Postgres storage adapter, and stronger auth for anyone who wants to run this in production. If that's the kind of thing you'd use, issues and PRs are open.

If you've built multi-agent systems, I'd like to hear how you handle memory today, especially episodic vs semantic, and whether a shared schema across frameworks would actually help or just move the problem.

---

*AMP is MIT licensed. Spec v0.1.0, reference server (FastAPI + ChromaDB), and clients for Python and Node.js are all in the repo.*
