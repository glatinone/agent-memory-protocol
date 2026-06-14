# FAQ

## How is AMP different from mem0 or Zep?

mem0 and Zep are managed memory services with their own data models and proprietary APIs — using them locks your agents into a specific vendor and SDK. AMP is an open protocol: it defines a standard schema (the `MemoryCell`) and a standard REST API that any server can implement. You can run the reference server yourself, swap it for a compatible implementation, or build a hosted product on top of it without changing agent code.

## Do I need to run my own server?

For now, yes — there is no hosted AMP service yet (see [Is there a hosted version?](#is-there-a-hosted-version)). The reference server runs in a single `docker compose up -d` command and stores data locally. Self-hosting is intentional for Phase 0/1: it keeps your memory data under your control and lets you validate the protocol before a hosted tier is offered.

## Can I use AMP without the Python SDK?

Yes. The Python SDK (`amp-client`) is a convenience wrapper and is fully available on PyPI (`pip install amp-client`). However, it is not strictly required. Everything the SDK does is available directly via the REST API — `POST /amp/v1/memories`, `POST /amp/v1/memories/search`, etc. Any HTTP client works: `curl`, `httpx`, `requests`, `fetch`, or any other language's HTTP library.

## What happens to a deleted memory — is it gone forever?

No. `DELETE /amp/v1/memories/{id}` is a soft-delete: it sets `lifecycle.status` to `"deleted"` and excludes the cell from all search results. The cell remains in storage and can still be retrieved directly by its ID. There is no hard-delete endpoint in v0.1.0; permanent removal requires direct storage access.

## How does decay work in plain English?

Every memory cell has an `importance` score, a `confidence` score, and a `decay_rate`. Each day that passes, the effective score drops according to `importance × confidence × e^(−decay_rate × days_since_creation)`. Once that score falls below `0.3`, the cell automatically transitions from `active` to `stale`. If it stays stale for 30 days without being updated, it transitions to `archived`. You can slow decay by setting a low `decay_rate` (e.g. `0.001`) or stop it by bumping `importance` or `confidence` via a PATCH.

## Can two agents share the same memory cell?

Yes. Access is controlled by `access_policy.readable_by` and `access_policy.writable_by`, which accept lists of agent IDs and support wildcard patterns (e.g. `"agent-team-*"`). Add both agent IDs to `readable_by` and they can both read the cell; add them to `writable_by` and either can update it. Setting `access_policy.public: true` makes a cell readable by any agent without listing each one explicitly. The cell's `owner_id` and `created_by` always retain full read and write access regardless of the policy.

## Does AMP work with LangChain / LlamaIndex?

Yes! The Python SDK (`amp-client`) includes native `AMPMemory` integration for LangChain, allowing you to plug AMP directly into LangChain chains and agents as a chat memory provider. For LlamaIndex, you can wrap the AMP REST API or client in a custom retriever manually — the API is simple enough that this takes under 50 lines. Contributions for LlamaIndex or other frameworks are welcome; see [How do I contribute to the spec?](#how-do-i-contribute-to-the-spec).

## Is there a hosted version?

Not yet. A hosted AMP service is on the roadmap but has not launched. The reference server is designed to be self-hosted with minimal ops burden (single container, local volume). Watch the [GitHub repository](https://github.com/AMP-Protocol/amp) for announcements when a hosted tier is available.

## How do I contribute to the spec?

Spec changes are proposed as RFCs in `amp/spec/rfcs/`. Open a pull request with a new markdown file describing the change — what it adds, why, and any backwards-compatibility impact. Protocol changes to existing fields or endpoint contracts require an RFC; adding examples, fixing typos, or improving docs can go straight to a PR. Discussion happens on the PR; approved RFCs are merged into the versioned spec under `amp/spec/v{version}/`.

## What's the difference between episodic, semantic, and procedural memory?

These map to the standard cognitive science taxonomy. **Episodic** memories are specific past events — "the user asked about Python in session-789." **Semantic** memories are facts and preferences that don't belong to a specific moment — "the user prefers Python for backend work." **Procedural** memories are how-to knowledge — "to answer a coding question, first clarify the language, then ask about constraints." Use `type` to tag cells accordingly; search filters let you query a single type when you only want, say, factual knowledge without conversational history.
