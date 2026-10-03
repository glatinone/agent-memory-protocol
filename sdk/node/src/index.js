/**
 * AMP Node.js SDK.
 *
 * ```js
 * import { AMPClient } from "amp-client";
 *
 * const client = new AMPClient("http://localhost:8765", "my-agent");
 * await client.remember("User prefers email", "user-123");
 * const hits = await client.recall("communication preference", "user-123");
 * ```
 */

export { AMPClient } from "./client.js";
export { AMPError } from "./errors.js";