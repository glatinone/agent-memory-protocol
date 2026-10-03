/**
 * Error raised for any non-2xx AMP response or transport failure.
 *
 * Mirrors `AMPError` in the Python SDK (`sdk/amp_client/exceptions.py`) so the
 * two clients fail the same way: a message, an HTTP status when there was one,
 * and the server's structured `error.details` when it sent them.
 */
export class AMPError extends Error {
  constructor(message, { statusCode = null, details = {} } = {}) {
    super(message);
    this.name = "AMPError";
    this.statusCode = statusCode;
    this.details = details;
  }
}
