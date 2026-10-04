/**
 * Tests for the Node AMP client.
 *
 * These run against a real AMP server when one is reachable, and skip
 * themselves when it is not, so the suite is useful in CI with a server up and
 * harmless without one. Requires AM{@code _AMP_TEST_URL} or the default below.
 *
 *   node --test sdk/node/test/
 *
 * No test framework is installed: `node:test` and `node:assert` ship with Node.
 */

import { test, describe, before } from "node:test";
import assert from "node:assert/strict";

import { AMPClient, AMPError } from "../src/index.js";

const SERVER_URL = process.env.AMP_TEST_URL ?? "http://127.0.0.1:8765";
const OWNER = `node-sdk-test-user-${Date.now()}`;

// Set by the probe in the live-server suite's `before`. Every live test checks
// it, because a `describe(..., { skip })` option is evaluated while the file is
// being collected, before any hook runs, and would always skip.
let serverUp = false;

describe("Paging", () => {
  // These capture the request the client actually makes. Asserting on a body
  // object built inside the test would prove nothing about the client.

  async function withCapturedFetch(run) {
    const calls = [];
    const original = globalThis.fetch;
    globalThis.fetch = async (url, init) => {
      calls.push({ url: String(url), init });
      return new Response(JSON.stringify({ results: [], returned: 0, has_more: false }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    };
    try {
      await run();
    } finally {
      globalThis.fetch = original;
    }
    return calls;
  }

  test("recall sends the offset in the request body", async () => {
    const client = new AMPClient("http://localhost:8000", "agent-1");

    const calls = await withCapturedFetch(() =>
      client.recall("a query", "user-123", { limit: 5, offset: 10 }),
    );

    assert.equal(JSON.parse(calls[0].init.body).offset, 10);
    assert.equal(JSON.parse(calls[0].init.body).limit, 5);
  });

  test("recall defaults to the first page", async () => {
    const client = new AMPClient("http://localhost:8000", "agent-1");

    const calls = await withCapturedFetch(() => client.recall("a query", "user-123"));

    assert.equal(JSON.parse(calls[0].init.body).offset, 0);
  });

  test("listMemories sends the offset in the query string", async () => {
    const client = new AMPClient("http://localhost:8000", "agent-1");

    const calls = await withCapturedFetch(() =>
      client.listMemories("user-123", { limit: 20, offset: 20 }),
    );

    assert.equal(new URL(calls[0].url).searchParams.get("offset"), "20");
  });
});

describe("API keys", () => {
  test("omits the key header unless one was given", () => {
    const client = new AMPClient("http://localhost:8000", "agent-1");
    assert.deepEqual(client._identityHeaders(), { "X-AMP-Agent-ID": "agent-1" });
  });

  test("carries the key header when one was given", () => {
    const client = new AMPClient("http://localhost:8000", "agent-1", "agent-one-key");
    assert.deepEqual(client._identityHeaders(), {
      "X-AMP-Agent-ID": "agent-1",
      "X-AMP-API-Key": "agent-one-key",
    });
  });

  test("lets a caller-supplied header win", () => {
    const client = new AMPClient("http://localhost:8000", "agent-1");
    assert.deepEqual(client._identityHeaders(), { "X-AMP-Agent-ID": "agent-1" });
  });
});

describe("URL normalization", () => {
  test("appends /amp/v1 when missing", () => {
    const client = new AMPClient("http://localhost:8000", "a");
    assert.equal(client.serverUrl, "http://localhost:8000/amp/v1");
  });

  test("handles a trailing slash", () => {
    const client = new AMPClient("http://localhost:8000/", "a");
    assert.equal(client.serverUrl, "http://localhost:8000/amp/v1");
  });

  test("leaves an explicit /amp/v1 intact", () => {
    const client = new AMPClient("http://localhost:8000/amp/v1", "a");
    assert.equal(client.serverUrl, "http://localhost:8000/amp/v1");
  });

  test("handles /amp/v1 with a trailing slash", () => {
    const client = new AMPClient("http://localhost:8000/amp/v1/", "a");
    assert.equal(client.serverUrl, "http://localhost:8000/amp/v1");
  });

  test("requires a server URL and agent ID", () => {
    assert.throws(() => new AMPClient("", "a"), AMPError);
    assert.throws(() => new AMPClient("http://x", ""), AMPError);
  });
});

describe("offline behaviour", () => {
  test("health() returns false for an unreachable server", async () => {
    // Port 1 is reserved and never listening.
    const client = new AMPClient("http://127.0.0.1:1", "a");
    assert.equal(await client.health(), false);
  });

  test("a transport failure raises AMPError, not a raw TypeError", async () => {
    const client = new AMPClient("http://127.0.0.1:1", "a");
    await assert.rejects(
      () => client.recall("q", OWNER),
      (err) => err instanceof AMPError && /HTTP request failed/.test(err.message),
    );
  });
});

describe("against a live server", () => {
  const client = new AMPClient(SERVER_URL, "node-test-agent");

  before(async () => {
    const probe = new AMPClient(SERVER_URL, "probe-agent");
    serverUp = await probe.health();
  });

  /** Every live test calls this first; see the note on `serverUp`. */
  const requireServer = (t) => {
    if (!serverUp) t.skip("no AMP server reachable");
    return serverUp;
  };

  test("remember returns a cell with a mem_ id", async (t) => {
    if (!requireServer(t)) return;
    const cell = await client.remember("User prefers email", OWNER);
    assert.match(cell.id, /^mem_/);
    assert.equal(cell.content.text, "User prefers email");
    assert.equal(cell.identity.owner_id, OWNER);
  });

  test("recall finds a previously stored memory", async (t) => {
    if (!requireServer(t)) return;
    await client.remember("User prefers dark mode", OWNER);
    const results = await client.recall("what theme does the user like", OWNER);
    assert.ok(results.length >= 1);
    assert.ok(results.some((c) => c.content.text === "User prefers dark mode"));
  });

  test("remember accepts a content object", async (t) => {
    if (!requireServer(t)) return;
    const cell = await client.remember(
      { text: "Has a cat named Milo", metadata: { topic: "pets" } },
      OWNER,
    );
    assert.equal(cell.content.metadata.topic, "pets");
  });

  test("listMemories returns this owner's cells", async (t) => {
    if (!requireServer(t)) return;
    const results = await client.listMemories(OWNER);
    assert.ok(results.length >= 1);
    assert.ok(results.every((c) => c.identity.owner_id === OWNER));
  });

  test("access control blocks an agent that is not in readable_by", async (t) => {
    if (!requireServer(t)) return;
    await client.remember("billing secret", OWNER, {
      readableBy: ["node-test-agent"],
    });
    const outsider = new AMPClient(SERVER_URL, "some-other-agent");
    const results = await outsider.recall("billing secret", OWNER);
    assert.equal(results.length, 0);
  });

  test("forget archives then deletes", async (t) => {
    if (!requireServer(t)) return;
    const cell = await client.remember("temporary", OWNER);
    assert.equal(await client.forget(cell.id), true);
  });

  test("a forgotten cell drops out of listMemories", async (t) => {
    if (!requireServer(t)) return;
    const cell = await client.remember("disappears after forget", OWNER);
    const before = await client.listMemories(OWNER);
    assert.ok(before.some((c) => c.id === cell.id));

    await client.forget(cell.id);

    const after = await client.listMemories(OWNER);
    assert.ok(!after.some((c) => c.id === cell.id));
  });

  test("forgetting an already-deleted cell raises AMPError", async (t) => {
    if (!requireServer(t)) return;
    const cell = await client.remember("deleted twice", OWNER);
    await client.forget(cell.id);

    // `deleted` is terminal and reads on it return a uniform 403, so the
    // second forget cannot even fetch the cell. This is the oracle-attack
    // behaviour from spec §8.4, observed from the client side.
    await assert.rejects(
      () => client.forget(cell.id),
      (err) => err instanceof AMPError && err.statusCode === 403,
    );
  });

  test("an unauthorized write is refused with AMPError", async (t) => {
    if (!requireServer(t)) return;
    const cell = await client.remember("owned by node-test-agent", OWNER, {
      readableBy: ["node-test-agent"],
    });
    const outsider = new AMPClient(SERVER_URL, "intruder-agent");
    await assert.rejects(
      () => outsider.forget(cell.id),
      (err) => err instanceof AMPError && err.statusCode === 403,
    );
  });
});