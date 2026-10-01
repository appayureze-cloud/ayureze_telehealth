import { describe, expect, it } from "vitest";

import {
  captionFromJson,
  participantRoleFromAttribute,
  sessionStatusFromString,
  userRoleFromString,
} from "../src/types";

describe("captionFromJson", () => {
  it("parses a normal (not blocked) caption", () => {
    const caption = captionFromJson({
      speaker_identity: "doctor-1",
      source_lang: "en",
      target_lang: "ta",
      original_text: "Take two tablets daily.",
      translated_text: "ஒரு நாளைக்கு இரண்டு மாத்திரைகள்.",
      blocked: false,
      timings_ms: { stt_ms: 120.5, translation_ms: 300 },
      at: 1700000000,
    });

    expect(caption.speakerIdentity).toBe("doctor-1");
    expect(caption.sourceLanguage).toBe("en");
    expect(caption.targetLanguage).toBe("ta");
    expect(caption.blocked).toBe(false);
    expect(caption.translatedText).not.toBeNull();
    expect(caption.timingsMs.stt_ms).toBe(120.5);
    expect(caption.at.getTime()).toBe(1700000000000);
  });

  it("parses a safety-blocked caption with a null translated_text", () => {
    const caption = captionFromJson({
      speaker_identity: "patient-1",
      source_lang: "ta",
      target_lang: "en",
      original_text: "சில அறிகுறிகள்",
      translated_text: null,
      blocked: true,
      timings_ms: {},
      at: 1700000000,
    });

    expect(caption.blocked).toBe(true);
    expect(caption.translatedText).toBeNull();
  });

  it("tolerates missing optional fields", () => {
    const caption = captionFromJson({});
    expect(caption.originalText).toBe("");
    expect(caption.blocked).toBe(false);
    expect(caption.timingsMs).toEqual({});
  });
});

describe("role/status parsing helpers", () => {
  it("userRoleFromString maps known + unknown values", () => {
    expect(userRoleFromString("doctor")).toBe("doctor");
    expect(userRoleFromString("admin")).toBe("admin");
    expect(userRoleFromString("patient")).toBe("patient");
    expect(userRoleFromString("bogus")).toBe("patient");
  });

  it("sessionStatusFromString maps known + unknown values", () => {
    expect(sessionStatusFromString("active")).toBe("active");
    expect(sessionStatusFromString("ended")).toBe("ended");
    expect(sessionStatusFromString("created")).toBe("created");
    expect(sessionStatusFromString("bogus")).toBe("created");
  });

  it("participantRoleFromAttribute maps known + unknown/undefined values", () => {
    expect(participantRoleFromAttribute("doctor")).toBe("doctor");
    expect(participantRoleFromAttribute("patient")).toBe("patient");
    expect(participantRoleFromAttribute("ai_agent")).toBe("ai_agent");
    expect(participantRoleFromAttribute(undefined)).toBe("unknown");
    expect(participantRoleFromAttribute("bogus")).toBe("unknown");
  });
});
