import { ApiError } from "./exceptions";
import {
  type AyurezeSessionState,
  type AyurezeUser,
  sessionStatusFromString,
  userRoleFromString,
} from "./types";

export interface AuthResult {
  accessToken: string;
  refreshToken: string;
  expiresAt: Date;
  user: AyurezeUser;
}

export interface JoinResult {
  livekitAccessToken: string;
  room: string;
  e2eeKeyBase64: string;
  session: AyurezeSessionState;
}

/**
 * Thin, directly-testable wrapper around the Go API's authenticated
 * endpoints (see docs/api/README.md). Accepts a custom `fetch` so it's
 * unit-testable without a network — see test/apiClient.test.ts.
 */
export class ApiClient {
  constructor(
    private readonly baseUrl: string,
    private readonly fetchImpl: typeof fetch = fetch,
  ) {}

  private async decodeOrThrow(resp: Response): Promise<Record<string, unknown>> {
    const text = await resp.text();
    const body = text ? (JSON.parse(text) as Record<string, unknown>) : {};
    if (resp.ok) return body;
    throw new ApiError(
      resp.status,
      (body.error as string) ?? "unknown_error",
      (body.message as string) ?? `request failed with status ${resp.status}`,
    );
  }

  private sessionFromJson(json: Record<string, unknown>): AyurezeSessionState {
    return {
      id: json.id as string,
      room: json.room as string,
      status: sessionStatusFromString((json.status as string) ?? "created"),
      aiTranslationAuthorized: (json.ai_translation_authorized as boolean) ?? false,
    };
  }

  async login(tenant: string, email: string, password: string): Promise<AuthResult> {
    const resp = await this.fetchImpl(`${this.baseUrl}/v1/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tenant, email, password }),
    });
    const json = await this.decodeOrThrow(resp);
    const userJson = json.user as Record<string, unknown>;
    return {
      accessToken: json.access_token as string,
      refreshToken: json.refresh_token as string,
      expiresAt: new Date(json.expires_at as string),
      user: {
        id: userJson.id as string,
        email: userJson.email as string,
        role: userRoleFromString((userJson.role as string) ?? "patient"),
        displayName: (userJson.display_name as string) ?? "",
      },
    };
  }

  async refresh(refreshToken: string): Promise<AuthResult> {
    const resp = await this.fetchImpl(`${this.baseUrl}/v1/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    const json = await this.decodeOrThrow(resp);
    const userJson = json.user as Record<string, unknown>;
    return {
      accessToken: json.access_token as string,
      refreshToken: json.refresh_token as string,
      expiresAt: new Date(json.expires_at as string),
      user: {
        id: userJson.id as string,
        email: userJson.email as string,
        role: userRoleFromString((userJson.role as string) ?? "patient"),
        displayName: (userJson.display_name as string) ?? "",
      },
    };
  }

  async logout(refreshToken: string): Promise<void> {
    await this.fetchImpl(`${this.baseUrl}/v1/auth/logout`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
  }

  async createSession(accessToken: string, patientEmail: string): Promise<AyurezeSessionState> {
    const resp = await this.fetchImpl(`${this.baseUrl}/v1/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
      body: JSON.stringify({ patient_email: patientEmail }),
    });
    return this.sessionFromJson(await this.decodeOrThrow(resp));
  }

  async joinSession(accessToken: string, sessionId: string): Promise<JoinResult> {
    const resp = await this.fetchImpl(`${this.baseUrl}/v1/sessions/${sessionId}/join`, {
      method: "POST",
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    const json = await this.decodeOrThrow(resp);
    return {
      livekitAccessToken: json.access_token as string,
      room: json.room as string,
      e2eeKeyBase64: json.e2ee_key as string,
      session: this.sessionFromJson(json.session as Record<string, unknown>),
    };
  }

  async endSession(accessToken: string, sessionId: string): Promise<AyurezeSessionState> {
    const resp = await this.fetchImpl(`${this.baseUrl}/v1/sessions/${sessionId}/end`, {
      method: "POST",
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    return this.sessionFromJson(await this.decodeOrThrow(resp));
  }

  async getSession(accessToken: string, sessionId: string): Promise<AyurezeSessionState> {
    const resp = await this.fetchImpl(`${this.baseUrl}/v1/sessions/${sessionId}`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    return this.sessionFromJson(await this.decodeOrThrow(resp));
  }

  async grantAiTranslationConsent(accessToken: string, sessionId: string): Promise<void> {
    const resp = await this.fetchImpl(
      `${this.baseUrl}/v1/sessions/${sessionId}/consent/ai-translation/grant`,
      { method: "POST", headers: { Authorization: `Bearer ${accessToken}` } },
    );
    await this.decodeOrThrow(resp);
  }

  async revokeAiTranslationConsent(accessToken: string, sessionId: string): Promise<void> {
    const resp = await this.fetchImpl(
      `${this.baseUrl}/v1/sessions/${sessionId}/consent/ai-translation/revoke`,
      { method: "POST", headers: { Authorization: `Bearer ${accessToken}` } },
    );
    await this.decodeOrThrow(resp);
  }
}
