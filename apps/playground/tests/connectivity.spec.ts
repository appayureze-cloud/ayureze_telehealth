import { test, expect, Page, Browser } from "@playwright/test";
import { loadRootEnv } from "./helpers/env";
import { craftToken, tamperSignature } from "./helpers/livekit-jwt";

const env = loadRootEnv();
const API_URL = `http://localhost:${env.API_HTTP_PORT ?? "8080"}`;
const LIVEKIT_URL = env.LIVEKIT_URL ?? "ws://localhost:7880";

function playgroundUrl(qs: Record<string, string>) {
  const params = new URLSearchParams({ apiUrl: API_URL, livekitUrl: LIVEKIT_URL, ...qs });
  return `/index.html?${params.toString()}`;
}

async function waitForPhase(page: Page, phase: string, timeout = 15_000) {
  await page.waitForFunction(
    (p) => (window as any).__ayureze?.getState()?.phase === p,
    phase,
    { timeout },
  );
}

async function getState(page: Page) {
  return page.evaluate(() => (window as any).__ayureze.getState());
}

async function newMediaContext(browser: Browser) {
  const ctx = await browser.newContext();
  await ctx.grantPermissions(["camera", "microphone"]);
  return ctx;
}

test.describe("patient/doctor connectivity", () => {
  test("patient and doctor join the same room, see and hear each other", async ({ browser }) => {
    const room = `e2e-room-${Date.now()}`;
    const patientCtx = await newMediaContext(browser);
    const doctorCtx = await newMediaContext(browser);
    const patient = await patientCtx.newPage();
    const doctor = await doctorCtx.newPage();

    await patient.goto(playgroundUrl({ role: "patient", room, identity: "patient-e2e" }));
    await doctor.goto(playgroundUrl({ role: "doctor", room, identity: "doctor-e2e" }));

    await waitForPhase(patient, "connected");
    await waitForPhase(doctor, "connected");

    // Each side should see the other as a remote participant.
    await patient.waitForFunction(
      () => (window as any).__ayureze.getState().remoteParticipants.includes("doctor-e2e"),
      undefined,
      { timeout: 15_000 },
    );
    await doctor.waitForFunction(
      () => (window as any).__ayureze.getState().remoteParticipants.includes("patient-e2e"),
      undefined,
      { timeout: 15_000 },
    );

    // Video: remote <video> element attached and actually decoding frames
    // (readyState >= HAVE_CURRENT_DATA and non-zero dimensions) — proves
    // video, not just signaling, works.
    const patientSeesDoctorVideo = await patient.waitForFunction(() => {
      const el = document.querySelector(
        `video[data-participant="doctor-e2e"][data-kind="video"]`,
      ) as HTMLVideoElement | null;
      return !!el && el.readyState >= 2 && el.videoWidth > 0;
    }, undefined, { timeout: 15_000 });
    expect(await patientSeesDoctorVideo.jsonValue()).toBeTruthy();

    const doctorSeesPatientVideo = await doctor.waitForFunction(() => {
      const el = document.querySelector(
        `video[data-participant="patient-e2e"][data-kind="video"]`,
      ) as HTMLVideoElement | null;
      return !!el && el.readyState >= 2 && el.videoWidth > 0;
    }, undefined, { timeout: 15_000 });
    expect(await doctorSeesPatientVideo.jsonValue()).toBeTruthy();

    // Audio: confirm an audio track was subscribed on both sides (fake mic
    // publishes a tone; presence of the subscribed audio track is the
    // meaningful signal in a headless environment with no real playback).
    const patientState = await getState(patient);
    const doctorState = await getState(doctor);
    expect(patientState.remoteTracksSubscribed).toContain("doctor-e2e:audio");
    expect(doctorState.remoteTracksSubscribed).toContain("patient-e2e:audio");

    await patientCtx.close();
    await doctorCtx.close();
  });

  test("disconnect and reconnect recovers the session", async ({ browser }) => {
    const room = `e2e-reconnect-${Date.now()}`;
    const ctx = await newMediaContext(browser);
    const page = await ctx.newPage();
    await page.goto(playgroundUrl({ role: "patient", room, identity: "reconnect-patient" }));
    await waitForPhase(page, "connected");

    await page.evaluate(() => (window as any).__ayureze.disconnect());
    await page.waitForFunction(
      () => (window as any).__ayureze.getState().phase === "disconnected",
      undefined,
      { timeout: 10_000 },
    );

    await page.evaluate(() => (window as any).__ayureze.connect());
    await waitForPhase(page, "connected");

    const state = await getState(page);
    expect(state.connectionState).toBe("connected");

    await ctx.close();
  });

  test("expired token is rejected", async ({ browser }) => {
    const token = craftToken({
      apiKey: env.LIVEKIT_API_KEY,
      apiSecret: env.LIVEKIT_API_SECRET,
      identity: "expired-patient",
      room: "e2e-expired",
      issuedAtSecondsAgo: 600,
      expiresInSeconds: -60, // expired 60s ago
    });
    const ctx = await browser.newContext();
    const page = await ctx.newPage();
    await page.goto(
      playgroundUrl({ role: "patient", room: "e2e-expired", identity: "expired-patient", token }),
    );

    await waitForPhase(page, "failed", 15_000);
    const state = await getState(page);
    expect(state.error).toBeTruthy();

    await ctx.close();
  });

  test("tampered/invalid token is rejected", async ({ browser }) => {
    const validShaped = craftToken({
      apiKey: env.LIVEKIT_API_KEY,
      apiSecret: env.LIVEKIT_API_SECRET,
      identity: "invalid-patient",
      room: "e2e-invalid",
    });
    const tampered = tamperSignature(validShaped);

    const ctx = await browser.newContext();
    const page = await ctx.newPage();
    await page.goto(
      playgroundUrl({ role: "patient", room: "e2e-invalid", identity: "invalid-patient", token: tampered }),
    );

    await waitForPhase(page, "failed", 15_000);
    const state = await getState(page);
    expect(state.error).toBeTruthy();

    await ctx.close();
  });

  test("rooms are isolated — a participant in room A never sees room B's participants", async ({
    browser,
  }) => {
    const roomA = `e2e-iso-a-${Date.now()}`;
    const roomB = `e2e-iso-b-${Date.now()}`;

    const ctxA1 = await newMediaContext(browser);
    const ctxA2 = await newMediaContext(browser);
    const ctxB1 = await newMediaContext(browser);

    const a1 = await ctxA1.newPage();
    const a2 = await ctxA2.newPage();
    const b1 = await ctxB1.newPage();

    await a1.goto(playgroundUrl({ role: "patient", room: roomA, identity: "a1" }));
    await a2.goto(playgroundUrl({ role: "doctor", room: roomA, identity: "a2" }));
    await b1.goto(playgroundUrl({ role: "patient", room: roomB, identity: "b1" }));

    await waitForPhase(a1, "connected");
    await waitForPhase(a2, "connected");
    await waitForPhase(b1, "connected");

    await a1.waitForFunction(
      () => (window as any).__ayureze.getState().remoteParticipants.includes("a2"),
      undefined,
      { timeout: 15_000 },
    );

    // Give room B a moment to (not) receive any cross-room participant event.
    await b1.waitForTimeout(2000);
    const b1State = await getState(b1);
    expect(b1State.remoteParticipants).not.toContain("a1");
    expect(b1State.remoteParticipants).not.toContain("a2");

    const a1State = await getState(a1);
    expect(a1State.remoteParticipants).not.toContain("b1");

    await ctxA1.close();
    await ctxA2.close();
    await ctxB1.close();
  });
});
