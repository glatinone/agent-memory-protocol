---
title: "My agents kept forgetting each other, so I wrote a protocol about it"
published: false
description: "Notes from building AMP, an open HTTP protocol for agent memory: what it defines, the five things I got wrong, and the question I still cannot answer."
tags: ai, python, opensource, programming
cover_image: 
---

I run a handful of agents on my laptop. One files notes for me, one answers questions about my projects, one watches news and tells me when something matters. Each of them is fine on its own. Together they are forgetful in a way that took me a while to name.

The notes agent knows I read email slowly and prefer short messages. The other two ask me every day how I want to be contacted.

It is not that the models are weak. Each agent has its own memory layer, its own storage, and its own idea of what a memory even is. LangChain has memory classes, LlamaIndex has its own, CrewAI and AutoGen have theirs. A LangChain agent cannot read a LlamaIndex agent's memory, and there is no agreed shape to hand over even if it could.

Anthropic's Model Context Protocol already solved the other half of this problem. Before MCP, every agent had a bespoke way to call a tool, and now there is a standard nobody has to think about. Memory never got that treatment. So one weekend I sat down to write the smallest thing that would fix it for my own setup, and then I kept going.

> **TL;DR:** MCP standardized how agents call tools. Nothing standardized how they remember. I wrote AMP, an open HTTP protocol for agent memory. This is what it defines, and the five things I got wrong building it.

## What I actually built

![Three agents from different frameworks talking to one AMP server over HTTP, which keeps cells in ChromaDB or PostgreSQL](FIGURE_ARCHITECTURE_PLACEHOLDER)

Three pieces, and I worked hard not to add a fourth.

**A memory cell.** One JSON shape for a memory: the content, who owns it, who created it, which session it came from, an importance score, and an access policy. If two agents disagree about what a memory is, nothing else in the design matters.

**A small REST API.** Plain HTTP under `/amp/v1`. Writing a memory is a POST with a JSON body. No SDK required, which matters more than it sounds: a protocol that only one language can speak is a library. There are clients for Python and Node anyway, but the wire format is the contract.

**A lifecycle.** Cells carry an importance score that decays over time, and a background job moves them from `active` to `stale` to `archived` as the score falls. This is the part I care about most, because it is the difference between a memory store and a leak. Context that stopped mattering should leave search results on its own.

> **TL;DR:** One JSON shape for a memory, a REST API under `/amp/v1` that any language can speak, and a decay engine that retires stale context without you writing a cron job.

## Sharing is the part I underestimated

Multi-agent memory only gets interesting when agents share it, and sharing needs permission. Permission belongs on the cell, not on the caller:

```json
{
  "access_policy": {
    "readable_by": ["agent_billing_*"],
    "writable_by": ["agent_customer_service"],
    "public": false
  }
}
```

Wildcards work, `public` defaults to false, and an agent that may not read a cell gets the same `403` whether the cell exists or not. That last part is deliberate. If invisible and deleted answered differently, error codes would become a way to probe for data you are not allowed to read.

![Agent A stores a preference, agent B reads it and gets 200 with one memory, agent C asks the same question and gets 403 with zero memories](FIGURE_ACCESS_PLACEHOLDER)

The demo in the repo runs exactly that scene with real agents: customer service stores a preference, billing reads it back, marketing asks the same question and gets nothing.

> **TL;DR:** Permission sits on the cell (`readable_by`, `writable_by`, `public: false`), and a cell you cannot read looks identical to a deleted one, so error codes cannot be used to probe.

## Memories that fade

Every cell has an importance score and a decay rate. The reference server runs a job that walks cells through `active`, then `stale`, then `archived` as the score drops, with the thresholds written down rather than buried in code (stale below 0.3, archived after 30 days). You can change the interval, or turn the job off and trigger runs yourself through an admin endpoint.

![Importance score falling over 60 days, crossing the 0.3 stale threshold and the 30 day archive threshold into the archived region](FIGURE_DECAY_PLACEHOLDER)

I also gave it a floor: a purge refuses to delete a cell inside a 30 day retention window, because "we keep your data for 30 days" is a promise you make to whoever stored it.

> **TL;DR:** Importance decays, cells fall through `active` to `stale` to `archived` on their own, and deletion refuses to beat the retention window the docs advertise.

## The five things I got wrong

This is the part I would want to read in someone else's post, so it goes in.

**1. I wrote the same rule twice.** Search did its own read check, and the storage layer had another one. They disagreed for exactly one kind of agent id, which a test caught by asserting that both callers give the same answer. There is one rule now, in one function, with a test that keeps it there. Duplicated policy is not a style problem, it is a bug waiting for its second caller.

**2. I documented a policy that nothing enforced.** The docstring said the retention window was enforced server side. The code would happily delete a cell a second after it was marked deleted, because the function that checked the window was called by nobody. The docs and the code disagreed, and the docs were winning. That is the worst version of that pair.

**3. My mocks passed while a method could never work.** The async client's `forget()` never marked a cell archived before deleting it, so every call came back `409`. The tests passed because a mock answered the DELETE and never modelled the precondition. Mocks do not know your rules. I added a small suite that runs against a real server, and then proved it can fail by putting the bug back.

**4. A route existed that could never be reached.** `GET /memories/query` was registered after `GET /memories/{memory_id}`, so the word "query" was parsed as a memory id. The endpoint was in the code, in the docs, and in the auth tests. It just never ran. The listing route is registered first now, and a test asserts it answers as itself.

**5. My first benchmark measured three things at once.** Each sample used a different query, so the table claimed 5000 cells were faster than 1000. I measured one repeated query instead, added a minimum column, and reran it on a quiet machine. The real numbers are in `docs/performance.md`, next to the parts they do not cover.

The through line is that every one of those was a claim that did not survive contact with a test. So I wrote a conformance suite that talks to a server over HTTP and imports nothing from my implementation. I can point it at someone else's server and get an honest answer about where it differs from the spec.

> **TL;DR:** Duplicated rules disagree. A documented policy that nothing enforces is worse than no policy. Mocks do not know your rules. Route registration order can make an endpoint unreachable. My first benchmark measured the wrong thing. Writing a conformance suite that imports nothing from the implementation is what made all five visible.

## What it is not yet

- **Published, but new.** `pip install amp-client` and `npm install @glatinone/amp-client`, both 0.1.0. Before this week you installed from the repo.
- **No hosted service.** You run it yourself, which I think is right for a protocol at this stage.
- **Clients for Python and Node only.** Go and Rust are the ones people ask for.
- **Storage is pluggable.** ChromaDB by default with no infrastructure, or PostgreSQL with `pgvector`. Both pass the same adapter contract tests.
- **Auth is opt-in and keys only.** Leave it off and the server trusts the `X-AMP-Agent-ID` header, which is what the spec describes for local use. Turn it on and a key is required, but there are no scopes, expiry or rotation yet, so an internet facing deployment still wants something in front of it.
- **The decay defaults are mine.** 0.3 and 30 days are numbers I picked, not numbers I validated against a real workload.

## Poking at it

```bash
git clone https://github.com/glatinone/agent-memory-protocol.git
cd agent-memory-protocol/server && docker compose up -d

# a memory shared with agent_billing_*, read back by an allowed agent
curl -s http://localhost:8765/amp/v1/memories/search \
  -H 'X-AMP-Agent-ID: agent_billing_v1' -H 'Content-Type: application/json' \
  -d '{"query": "contact preference", "owner_id": "user_123", "limit": 3}'
```

Repo: https://github.com/glatinone/agent-memory-protocol
Spec and docs: https://glatinone.github.io/agent-memory-protocol/
Conformance suite: `conformance/` in the repo, 39 vectors, HTTP only, no dependency on the reference server.

## What I would like to know

If you run multi-agent systems, how do you handle memory today? Do you keep episodic and semantic memory separate, or treat them as one thing with different scores? And does a shared schema across frameworks actually help, or does it just move the problem somewhere else?

I am genuinely unsure about that last one. A protocol is only worth the agreement people give it, and I would rather be told the idea is wrong now than after more people depend on it. Issues and PRs are open.
