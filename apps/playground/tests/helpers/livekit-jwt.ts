import jwt from "jsonwebtoken";

/**
 * Crafts a LiveKit-shaped access token directly (bypassing the Go API) so
 * tests can exercise LiveKit's own rejection of expired/tampered tokens,
 * independent of the Go service's TTL policy. Claim shape mirrors
 * apps/api/internal/token (github.com/livekit/protocol/auth ClaimGrants).
 */
export function craftToken(opts: {
  apiKey: string;
  apiSecret: string;
  identity: string;
  room: string;
  issuedAtSecondsAgo?: number;
  expiresInSeconds?: number; // negative => already expired
}): string {
  const now = Math.floor(Date.now() / 1000);
  const iat = now - (opts.issuedAtSecondsAgo ?? 0);
  const exp = now + (opts.expiresInSeconds ?? 300);

  const payload = {
    iss: opts.apiKey,
    sub: opts.identity,
    iat,
    nbf: iat,
    exp,
    identity: opts.identity,
    video: {
      roomJoin: true,
      room: opts.room,
      canPublish: true,
      canSubscribe: true,
      canPublishData: true,
    },
    attributes: { role: "patient" },
  };

  return jwt.sign(payload, opts.apiSecret, { algorithm: "HS256", noTimestamp: true });
}

/** Returns a syntactically-valid but signature-tampered version of a token. */
export function tamperSignature(token: string): string {
  const parts = token.split(".");
  const sig = parts[2];
  const flipped = sig.slice(0, -4) + (sig.slice(-4) === "AAAA" ? "BBBB" : "AAAA");
  return `${parts[0]}.${parts[1]}.${flipped}`;
}
