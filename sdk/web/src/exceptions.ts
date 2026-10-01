/** Base type for every error this SDK throws. */
export abstract class AyurezeError extends Error {}

/** An SDK method was called before initialize()/authenticate(). */
export class NotInitializedError extends AyurezeError {
  constructor(message: string) {
    super(message);
    this.name = "NotInitializedError";
  }
}

/**
 * The Go API rejected a request. `statusCode`/`errorCode` mirror the Go
 * API's `{"error": "<code>", "message": "..."}` response shape (see
 * docs/api/README.md).
 */
export class ApiError extends AyurezeError {
  constructor(
    public readonly statusCode: number,
    public readonly errorCode: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Failed to connect to, or was disconnected from, the LiveKit room. */
export class ConnectionError extends AyurezeError {
  constructor(message: string) {
    super(message);
    this.name = "ConnectionError";
  }
}
