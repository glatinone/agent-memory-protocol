/**
 * AMP client for Node.js.
 *
 * A dependency-free port of the Python SDK (`sdk/amp_client/`). Node 18+ ships
 * `fetch`, so this needs no packages at all: no HTTP library, no build step,
 * no lockfile. Types come from JSDoc, which editors understand, so there is
 * nothing to compile and no separate `.d.ts` to drift out of sync.
 */

import { AMPError } from "./errors.js";

/**
 * @typedef {Object} MemoryCell
 * @property {string} id
 * @property {"episodic" | "semantic" | "procedural"} type
 * @property {{ text: string, metadata?: Record<string, unknown> }} content
 * @property {Object} identity
 * @property {Object} lifecycle
 * @property {Object} scoring
 * @property {Object} [access_policy]
 */

/**
 * @typedef {Object} RememberOptions
 * @property {string} [type]         Memory type (default "semantic").
 * @property {number} [importance]   Importance score, 0 to 1 (default 0.5).
 * @property {string[]} [readableBy] Agent ID patterns allowed to read this cell.
 */

/**
 * @typedef {Object} RecallOptions
 * @property {number} [limit]        Maximum results (default 5).
 * @property {boolean} [includeStale] Include stale cells in results.
 */

export class AMPClient {
  /**
   * @param {string} serverUrl Base URL of the AMP server.
   * @param {string} agentId   Identifier of this agent, sent as `X-AMP-Agent-ID`.
   * @param {string} [apiKey]   Key belonging to `agentId`, sent as
   *   `X-AMP-API-Key`. Only needed when the server is run with
   *   `AMP_API_KEYS_FILE`; otherwise the agent id alone is accepted.
   */
  constructor(serverUrl, agentId, apiKey) {
    if (!serverUrl) throw new AMPError("serverUrl is required");
    if (!agentId) throw new AMPError("agentId is required");

    // Mirror the Python SDK's normalization so both clients accept the same
    // inputs: a bare host with or without a trailing slash, or an explicit
    // `/amp/v1`, all resolve to the same endpoint prefix.
    const normalized = serverUrl.replace(/\/+$/, "");
    this.serverUrl = normalized.endsWith("/amp/v1")
      ? normalized
      : `${normalized}/amp/v1`;
    this.agentId = agentId;
    this.apiKey = apiKey;
  }

  /**
   * The headers that identify this client, built in one place so no call path
   * can be missing the credential.
   *
   * @returns {Record<string, string>}
   * @private
   */
  _identityHeaders() {
    const headers = { "X-AMP-Agent-ID": this.agentId };
    if (this.apiKey) headers["X-AMP-API-Key"] = this.apiKey;
    return headers;
  }

  /**
   * Execute a request and turn non-2xx responses into AMPError.
   *
   * @param {string} method
   * @param {string} path
   * @param {Object} [options]
   * @param {unknown} [options.body]  JSON-serializable request body.
   * @param {Record<string, string>} [options.headers]
   * @returns {Promise<Response>}
   * @private
   */
  async _request(method, path, { body, headers = {} } = {}) {
    const url = new URL(`${this.serverUrl}${path}`);

    const finalHeaders = { ...this._identityHeaders(), ...headers };
    let payload;
    if (body !== undefined) {
      finalHeaders["Content-Type"] = "application/json";
      payload = JSON.stringify(body);
    }

    let response;
    try {
      response = await fetch(url, {
        method,
        headers: finalHeaders,
        body: payload,
      });
    } catch (cause) {
      // Network-level failure (refused, DNS, timeout) rather than an HTTP
      // status. Wrap it so callers only ever catch AMPError.
      throw new AMPError(`HTTP request failed: ${cause.message}`);
    }

    if (!response.ok) {
      throw await AMPClient._toAMPError(response);
    }
    return response;
  }

  /**
   * Build an AMPError from an error response, preferring the server's own
   * `error.code` / `error.message` over the raw body.
   *
   * @param {Response} response
   * @returns {Promise<AMPError>}
   * @private
   */
  static async _toAMPError(response) {
    let message = `HTTP error ${response.status}`;
    let details = {};
    try {
      const body = await response.json();
      const error = body?.error;
      if (error && typeof error === "object") {
        message =
          error.code && error.message
            ? `${error.code}: ${error.message}`
            : (error.message ?? message);
        details = error.details ?? {};
      }
    } catch {
      // Non-JSON error body; keep the generic message.
    }
    return new AMPError(message, {
      statusCode: response.status,
      details,
    });
  }

  /**
   * Create a memory cell.
   *
   * @param {string | { text: string, metadata?: Record<string, unknown> }} content
   * @param {string} ownerId
   * @param {RememberOptions} [options]
   * @returns {Promise<MemoryCell>}
   */
  async remember(content, ownerId, options = {}) {
    const { type = "semantic", importance = 0.5, readableBy } = options;

    const contentPayload =
      typeof content === "string"
        ? { text: content, metadata: {} }
        : content;

    /** @type {Record<string, unknown>} */
    const body = {
      type,
      content: contentPayload,
      identity: { owner_id: ownerId, owner_type: "user" },
      scoring: { importance },
    };
    if (readableBy !== undefined) {
      body.access_policy = { readable_by: readableBy };
    }

    const response = await this._request("POST", "/memories", { body });
    return response.json();
  }

  /**
   * Semantic search over memory cells.
   *
   * @param {string} query
   * @param {string} ownerId
   * @param {RecallOptions} [options]
   * @returns {Promise<MemoryCell[]>}
   */
  async recall(query, ownerId, options = {}) {
    const { limit = 5, includeStale = false } = options;

    const response = await this._request("POST", "/memories/search", {
      body: {
        query,
        owner_id: ownerId,
        limit,
        include_stale: includeStale,
      },
    });
    const data = await response.json();
    return data.results ?? [];
  }

  /**
   * Archive then soft-delete a memory cell.
   *
   * The server only permits `archived -> deleted`, so this PATCHes to
   * `archived` first. The PATCH body must carry the cell's existing
   * `created_at` because the whole `lifecycle` object is validated on write.
   *
   * @param {string} memoryId
   * @returns {Promise<boolean>} True when the delete returned 204.
   */
  async forget(memoryId) {
    const cell = await (
      await this._request("GET", `/memories/${memoryId}`)
    ).json();
    const createdAt = cell.lifecycle.created_at;

    await this._request("PATCH", `/memories/${memoryId}`, {
      body: { lifecycle: { created_at: createdAt, status: "archived" } },
    });

    const response = await this._request("DELETE", `/memories/${memoryId}`);
    return response.status === 204;
  }

  /**
   * List memory cells by owner, without semantic search.
   *
   * @param {string} ownerId
   * @param {{ type?: string, limit?: number }} [options]
   * @returns {Promise<MemoryCell[]>}
   */
  async listMemories(ownerId, options = {}) {
    const { type, limit = 20 } = options;

    const params = new URLSearchParams({
      owner_id: ownerId,
      limit: String(limit),
    });
    if (type !== undefined) params.set("type", type);

    const response = await this._request("GET", `/memories?${params}`);
    const data = await response.json();
    return data.results ?? [];
  }

  /**
   * Check server health.
   *
   * Returns false rather than throwing on an unreachable server, matching the
   * Python client: a health probe should answer the question, not raise.
   *
   * @returns {Promise<boolean>}
   */
  async health() {
    try {
      const response = await this._request("GET", "/health");
      const data = await response.json();
      return data.status === "ok";
    } catch {
      return false;
    }
  }
}