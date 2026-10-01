import { type ChildProcess, spawn } from "node:child_process";
import path from "node:path";
import readline from "node:readline";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PYTHON = path.resolve(__dirname, "../../../ai-agent/.venv/bin/python3");
const SCRIPT = path.resolve(__dirname, "./native_participant.py");

export interface NativeParticipantHandle {
  proc: ChildProcess;
  sessionId: string;
  room: string;
  identity: string;
  /** Resolves once the process exits, with its parsed "done" event (or throws on error/timeout). */
  waitDone(): Promise<{ encryption_errors: { event: string; participant: string; error: string }[] }>;
  kill(): void;
}

interface CreateAndJoinOpts {
  tenant: string;
  doctorEmail: string;
  doctorPassword: string;
  patientEmail: string;
  role: "doctor" | "patient";
  apiBaseUrl: string;
  livekitUrl: string;
  durationSeconds: number;
  publishAudio: boolean;
}

/** Spawns the real native LiveKit participant and resolves once it reports "ready" (connected, key applied, optionally publishing) — the process keeps running until durationSeconds elapses or kill() is called. */
export function spawnNativeCreateAndJoin(opts: CreateAndJoinOpts): Promise<NativeParticipantHandle> {
  const args = [
    SCRIPT,
    "create-and-join",
    "--tenant", opts.tenant,
    "--doctor-email", opts.doctorEmail,
    "--doctor-password", opts.doctorPassword,
    "--patient-email", opts.patientEmail,
    "--role", opts.role,
    "--api-base-url", opts.apiBaseUrl,
    "--livekit-url", opts.livekitUrl,
    "--duration-seconds", String(opts.durationSeconds),
  ];
  if (opts.publishAudio) args.push("--publish-audio");
  return spawnAndWaitReady(args);
}

export function spawnNativeJoin(opts: {
  tenant: string;
  email: string;
  password: string;
  sessionId: string;
  apiBaseUrl: string;
  livekitUrl: string;
  durationSeconds: number;
  publishAudio: boolean;
}): Promise<NativeParticipantHandle> {
  const args = [
    SCRIPT,
    "join",
    "--tenant", opts.tenant,
    "--email", opts.email,
    "--password", opts.password,
    "--session-id", opts.sessionId,
    "--api-base-url", opts.apiBaseUrl,
    "--livekit-url", opts.livekitUrl,
    "--duration-seconds", String(opts.durationSeconds),
  ];
  if (opts.publishAudio) args.push("--publish-audio");
  return spawnAndWaitReady(args);
}

function spawnAndWaitReady(args: string[]): Promise<NativeParticipantHandle> {
  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON, args, { stdio: ["ignore", "pipe", "pipe"] });
    const rl = readline.createInterface({ input: proc.stdout! });
    let settled = false;
    let doneResolvers: ((v: { encryption_errors: any[] }) => void)[] = [];
    let doneRejecters: ((e: Error) => void)[] = [];
    let doneResult: { encryption_errors: any[] } | null = null;

    let stderrBuf = "";
    proc.stderr!.on("data", (d) => (stderrBuf += d.toString()));

    rl.on("line", (line) => {
      let parsed: any;
      try {
        parsed = JSON.parse(line);
      } catch {
        return; // non-JSON noise on stdout — ignore
      }
      if (parsed.event === "ready" && !settled) {
        settled = true;
        resolve({
          proc,
          sessionId: parsed.session_id,
          room: parsed.room,
          identity: parsed.identity,
          waitDone: () =>
            new Promise((res, rej) => {
              if (doneResult) return res(doneResult);
              doneResolvers.push(res);
              doneRejecters.push(rej);
            }),
          kill: () => proc.kill("SIGTERM"),
        });
      } else if (parsed.event === "done") {
        doneResult = parsed;
        doneResolvers.forEach((r) => r(parsed));
      } else if (parsed.event === "error") {
        const err = new Error(`native_participant.py error: ${parsed.error}\n${stderrBuf}`);
        if (!settled) {
          settled = true;
          reject(err);
        }
        doneRejecters.forEach((r) => r(err));
      }
    });

    proc.on("exit", (code) => {
      if (!settled) {
        settled = true;
        reject(new Error(`native_participant.py exited with code ${code} before reporting ready.\n${stderrBuf}`));
        return;
      }
      // Process exited (e.g. via kill()) without ever printing a "done"
      // line — SIGTERM interrupts the script mid-sleep, before it reaches
      // its own emit({"event": "done", ...}) call. Without this, any
      // pending waitDone() callers hang forever (neither resolved nor
      // rejected). Resolve with an empty result: kill() is only ever
      // called after the caller is done observing errors, so there is
      // nothing further to report.
      if (!doneResult) {
        doneResult = { encryption_errors: [] };
        doneResolvers.forEach((r) => r(doneResult!));
      }
    });

    setTimeout(() => {
      if (!settled) {
        settled = true;
        proc.kill("SIGKILL");
        reject(new Error(`native_participant.py did not become ready within 20s.\n${stderrBuf}`));
      }
    }, 20_000);
  });
}
