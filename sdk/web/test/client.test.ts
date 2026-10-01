import { describe, expect, it } from "vitest";

import { AyurezeTelehealthClient } from "../src/client";
import { ConnectionError, NotInitializedError } from "../src/exceptions";

function newClient() {
  return new AyurezeTelehealthClient({ apiBaseUrl: "https://api.test", livekitUrl: "wss://lk.test" });
}

describe("AyurezeTelehealthClient guard rails", () => {
  it("authenticate() before initialize() throws NotInitializedError", async () => {
    const client = newClient();
    await expect(client.authenticate("t", "e", "p")).rejects.toBeInstanceOf(NotInitializedError);
  });

  it("createSession() before authenticate() throws NotInitializedError", async () => {
    const client = newClient();
    await client.initialize();
    await expect(client.createSession("p@example.com")).rejects.toBeInstanceOf(NotInitializedError);
  });

  it("enableMicrophone() before joinSession() throws ConnectionError", async () => {
    const client = newClient();
    await client.initialize();
    await expect(client.enableMicrophone()).rejects.toBeInstanceOf(ConnectionError);
  });

  it("getConnectionState() is disconnected before any join", async () => {
    const client = newClient();
    await client.initialize();
    expect(client.getConnectionState()).toBe("disconnected");
  });

  it("getParticipants() is empty before any join", async () => {
    const client = newClient();
    await client.initialize();
    expect(client.getParticipants()).toEqual([]);
  });

  it("getSessionState() is null before createSession/joinSession", async () => {
    const client = newClient();
    await client.initialize();
    expect(client.getSessionState()).toBeNull();
  });

  it("setLanguage()/preferredLanguage round-trips without requiring auth", () => {
    const client = newClient();
    expect(client.preferredLanguage).toBe("en");
    client.setLanguage("ta");
    expect(client.preferredLanguage).toBe("ta");
  });
});
