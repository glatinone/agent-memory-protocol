# AMP Node.js Client SDK

Node.js client for the **Agent Memory Protocol (AMP)**. Mirrors the Python SDK's
API surface (`sdk/amp_client/`) so agents written in either language talk to the
same server the same way.

## Install

Not published to npm yet. Use it from a clone:

```bash
npm install ./sdk/node
```

**No dependencies.** Node 18 and later ship `fetch`, so this client needs no HTTP
library, no build step, and no lockfile. Types come from JSDoc, which editors
read, so there is nothing to compile and no separate type definitions to drift
out of sync.

## Quickstart

```js
import { AMPClient } from "@glatinone/amp-client";

const client = new AMPClient("http://localhost:8765", "my-agent");

await client.remember("User prefers email over phone", "user-123");

const hits = await client.recall("how does the user want to be contacted?", "user-123");
console.log(hits[0].content.text);
```

## API

All methods are async. `serverUrl` is normalized the same way as the Python
client: a bare host, a host with a trailing slash, or an explicit `/amp/v1` all
resolve to the same endpoint prefix.

### `new AMPClient(serverUrl, agentId)`

- `serverUrl` - base URL of the AMP server.
- `agentId` - this agent's identifier, sent as the `X-AMP-Agent-ID` header.

### `remember(content, ownerId, options?)`

Stores a memory. `content` is either a string or a `{ text, metadata }` object.

Options:

| Option | Type | Default | Meaning |
|---|---|---|---|
| `type` | `"semantic" \| "episodic" \| "procedural"` | `"semantic"` | Memory type |
| `importance` | number, 0 to 1 | `0.5` | Importance score |
| `readableBy` | `string[]` | none | Agent ID patterns allowed to read this cell |

Returns the created cell.

### `recall(query, ownerId, options?)`

Semantic search. Options: `limit` (default 5), `includeStale` (default false).
Returns an array of matching cells, ranked by blended similarity and decay score.

### `listMemories(ownerId, options?)`

Lists cells by owner without semantic search. Options: `type`, `limit` (default
20).

### `forget(memoryId)`

Archives then soft-deletes a cell, and returns `true` on success. The server
only permits `archived -> deleted`, so this archives first. The cell's data is
retained for the 30-day audit window described in the spec.

### `health()`

Returns `true` if the server reports healthy, `false` if it is unreachable.
Never throws: a health probe should answer the question, not raise.

## Errors

Any non-2xx response or transport failure throws `AMPError`, with `statusCode`
and `details` when the server provided them.

```js
import { AMPClient, AMPError } from "@glatinone/amp-client";

try {
  await client.remember("", "user-123");
} catch (err) {
  if (err instanceof AMPError) {
    console.error(err.message, err.statusCode, err.details);
  }
}
```

## Tests

```bash
npm test
```

Runs the `node:test` runner built into Node. The suite has two halves: offline
tests that always run (URL normalization, transport failures), and integration
tests against a live server at `http://127.0.0.1:8765` that skip themselves when
no server is reachable. Point them elsewhere with `AMP_TEST_URL`.
