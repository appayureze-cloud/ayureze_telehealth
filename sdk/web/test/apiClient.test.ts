import { describe, expect, it, vi } from "vitest";

import { ApiClient } from "../src/apiClient";
import { ApiError } from "../src/exceptions";

function fakeFetch(handler: (input: RequestInfo | URL, init?: RequestInit) => Response): typeof fetch {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => handler(input, init)) as unknown as typeof fetch;
}

describe("ApiClient.login", () => {
  it("sends tenant/email/password and parses a successful response", async () => {
    let capturedBody: unknown;
    let capturedUrl: string | undefined;
    const client = new ApiClient(
      "https://api.test",
      fakeFetch((input, init) => {
        capturedUrl = String(input);
        capturedBody = JSON.parse(init?.body as string);
        return new Response(
          JSON.stringify({
            access_token: "access-123",
            refresh_token: "refresh-456",
            expires_at: "2030-01-01T00:00:00Z",
            user: { id: "user-1", email: "doctor@example.com", role: "doctor", display_name: "Dr. Test" },
          }),
          { status: 200 },
        );
      }),
    );

    const result = await client.login("clinic-1", "doctor@example.com", "secret");

    expect(capturedUrl).toBe("https://api.test/v1/auth/login");
    expect(capturedBody).toEqual({ tenant: "clinic-1", email: "doctor@example.com", password: "secret" });
    expect(result.accessToken).toBe("access-123");
    expect(result.user.role).toBe("doctor");
    expect(result.user.displayName).toBe("Dr. Test");
  });

  it("throws ApiError with the error code/message on 401", async () => {
    const client = new ApiClient(
      "https://api.test",
      fakeFetch(
        () =>
          new Response(JSON.stringify({ error: "unauthorized", message: "invalid credentials" }), {
            status: 401,
          }),
      ),
    );

    await expect(client.login("clinic-1", "x@example.com", "wrong")).rejects.toMatchObject(
      new ApiError(401, "unauthorized", "invalid credentials"),
    );
  });
});

describe("ApiClient.joinSession", () => {
  it("parses access token, room, e2ee key, and nested session", async () => {
    let capturedUrl: string | undefined;
    let capturedAuth: string | undefined | null;
    const client = new ApiClient(
      "https://api.test",
      fakeFetch((input, init) => {
        capturedUrl = String(input);
        capturedAuth = (init?.headers as Record<string, string>)?.Authorization;
        return new Response(
          JSON.stringify({
            access_token: "lk-token",
            room: "session-room-1",
            e2ee_key: "base64key==",
            expires_at: "2030-01-01T00:00:00Z",
            session: { id: "session-1", room: "session-room-1", status: "active", ai_translation_authorized: false },
          }),
          { status: 200 },
        );
      }),
    );

    const result = await client.joinSession("token-abc", "session-1");

    expect(capturedUrl).toBe("https://api.test/v1/sessions/session-1/join");
    expect(capturedAuth).toBe("Bearer token-abc");
    expect(result.livekitAccessToken).toBe("lk-token");
    expect(result.e2eeKeyBase64).toBe("base64key==");
    expect(result.session.status).toBe("active");
  });
});

describe("ApiClient consent endpoints", () => {
  it("grantAiTranslationConsent posts to the grant endpoint", async () => {
    let calledUrl: string | undefined;
    const client = new ApiClient(
      "https://api.test",
      fakeFetch((input) => {
        calledUrl = String(input);
        return new Response(JSON.stringify({ status: "granted" }), { status: 200 });
      }),
    );
    await client.grantAiTranslationConsent("t", "s1");
    expect(calledUrl).toBe("https://api.test/v1/sessions/s1/consent/ai-translation/grant");
  });

  it("revokeAiTranslationConsent posts to the revoke endpoint", async () => {
    let calledUrl: string | undefined;
    const client = new ApiClient(
      "https://api.test",
      fakeFetch((input) => {
        calledUrl = String(input);
        return new Response(JSON.stringify({ status: "revoked" }), { status: 200 });
      }),
    );
    await client.revokeAiTranslationConsent("t", "s1");
    expect(calledUrl).toBe("https://api.test/v1/sessions/s1/consent/ai-translation/revoke");
  });
});
