/// Public data models returned by [AyurezeTelehealthClient]. Kept free of
/// any LiveKit or `http` package types so consuming apps never need to
/// import those directly — the whole point of a headless SDK.
library;

/// Mirrors `internal/domain.Role` on the Go API (patient/doctor/admin).
enum AyurezeUserRole { patient, doctor, admin }

AyurezeUserRole userRoleFromString(String value) => switch (value) {
      'doctor' => AyurezeUserRole.doctor,
      'admin' => AyurezeUserRole.admin,
      _ => AyurezeUserRole.patient,
    };

class AyurezeUser {
  final String id;
  final String email;
  final AyurezeUserRole role;
  final String displayName;

  const AyurezeUser({
    required this.id,
    required this.email,
    required this.role,
    required this.displayName,
  });
}

/// Mirrors `internal/domain.SessionStatus`.
enum AyurezeSessionStatus { created, active, ended }

AyurezeSessionStatus sessionStatusFromString(String value) => switch (value) {
      'active' => AyurezeSessionStatus.active,
      'ended' => AyurezeSessionStatus.ended,
      _ => AyurezeSessionStatus.created,
    };

class AyurezeSessionState {
  final String id;
  final String room;
  final AyurezeSessionStatus status;
  final bool aiTranslationAuthorized;

  const AyurezeSessionState({
    required this.id,
    required this.room,
    required this.status,
    required this.aiTranslationAuthorized,
  });
}

/// Connection state to the LiveKit room — a small, SDK-owned enum so
/// callers never need to import `livekit_client`'s own ConnectionState.
enum AyurezeConnectionState { disconnected, connecting, connected, reconnecting }

enum AyurezeParticipantRole { patient, doctor, aiAgent, unknown }

AyurezeParticipantRole participantRoleFromAttribute(String? value) => switch (value) {
      'patient' => AyurezeParticipantRole.patient,
      'doctor' => AyurezeParticipantRole.doctor,
      'ai_agent' => AyurezeParticipantRole.aiAgent,
      _ => AyurezeParticipantRole.unknown,
    };

class AyurezeParticipant {
  final String identity;
  final AyurezeParticipantRole role;
  final bool audioEnabled;
  final bool videoEnabled;
  final bool isLocal;

  const AyurezeParticipant({
    required this.identity,
    required this.role,
    required this.audioEnabled,
    required this.videoEnabled,
    required this.isLocal,
  });
}

/// A live or translated caption delivered over the AI agent's data
/// channel (`ayureze.captions` topic — see
/// apps/ai-agent/app/pipeline/streaming.py).
class AyurezeCaption {
  final String speakerIdentity;
  final String sourceLanguage;
  final String targetLanguage;
  final String originalText;
  final String? translatedText;
  final bool blocked;
  final Map<String, double> timingsMs;
  final DateTime at;

  const AyurezeCaption({
    required this.speakerIdentity,
    required this.sourceLanguage,
    required this.targetLanguage,
    required this.originalText,
    required this.translatedText,
    required this.blocked,
    required this.timingsMs,
    required this.at,
  });

  factory AyurezeCaption.fromJson(Map<String, dynamic> json) {
    return AyurezeCaption(
      speakerIdentity: json['speaker_identity'] as String? ?? '',
      sourceLanguage: json['source_lang'] as String? ?? '',
      targetLanguage: json['target_lang'] as String? ?? '',
      originalText: json['original_text'] as String? ?? '',
      translatedText: json['translated_text'] as String?,
      blocked: json['blocked'] as bool? ?? false,
      timingsMs: (json['timings_ms'] as Map<String, dynamic>? ?? {})
          .map((k, v) => MapEntry(k, (v as num).toDouble())),
      at: DateTime.fromMillisecondsSinceEpoch(
        (((json['at'] as num?) ?? 0).toDouble() * 1000).round(),
      ),
    );
  }
}

/// Per-track LiveKit E2EE state, mirrored 1:1 from `livekit_client`'s own
/// `E2EEState` enum (`kNew` renamed to [pending] since `new` is a Dart
/// keyword) plus an [unknown] fallback for any state this SDK doesn't
/// recognize. Never invented or inferred — always set from a real
/// `TrackE2EEStateEvent` LiveKit itself emitted.
///
/// [isSecure] is the fail-closed check every caller should use: it is
/// `false` for every state except [ok] and [keyRatcheted], including
/// [pending] (not yet confirmed) and [unknown] (unrecognized) — a track
/// is never assumed secure absent an explicit, current, positive
/// confirmation from LiveKit.
enum AyurezeE2EEState {
  /// Not yet confirmed either way (LiveKit's `E2EEState.kNew`).
  pending,

  /// Actively encrypting/decrypting successfully (LiveKit's `kOk`).
  ok,

  /// The key was rotated; still secure (LiveKit's `kKeyRatcheted`).
  keyRatcheted,

  /// No usable key is available for this track (LiveKit's `kMissingKey`).
  missingKey,

  /// The local encrypted publish path failed (LiveKit's
  /// `kEncryptionFailed`).
  encryptionFailed,

  /// A received frame could not be decrypted (LiveKit's
  /// `kDecryptionFailed`) — e.g. a wrong or incompatible key.
  decryptionFailed,

  /// An internal cryptor error (LiveKit's `kInternalError`).
  internalError,

  /// A state this SDK does not recognize. Always treated as NOT secure.
  unknown;

  /// Fail-closed: true only for the two states LiveKit itself reports as
  /// actively secure. Every other state — including [pending], the state
  /// before any confirmation — is NOT currently secure.
  bool get isSecure => this == AyurezeE2EEState.ok || this == AyurezeE2EEState.keyRatcheted;
}

/// Mirrors `livekit_client`'s `TrackType` (audio/video/data), so callers
/// never need to import LiveKit types directly.
enum AyurezeTrackKind { audio, video, data, unknown }

/// A safe, loggable snapshot of one track's E2EE state at a point in
/// time. Deliberately carries only identifiers and a state
/// classification — never encryption keys, ciphertext, plaintext, raw
/// media, access tokens, or other session secrets.
///
/// Identified by [trackSid] (a stable LiveKit-assigned id), never by a
/// display name, so state tracking survives renames and disambiguates
/// participants with the same identity across reconnects.
class AyurezeE2EETrackState {
  final String participantIdentity;
  final bool isLocalParticipant;
  final String trackSid;
  final AyurezeTrackKind kind;
  final AyurezeE2EEState state;
  final DateTime at;

  const AyurezeE2EETrackState({
    required this.participantIdentity,
    required this.isLocalParticipant,
    required this.trackSid,
    required this.kind,
    required this.state,
    required this.at,
  });

  @override
  String toString() => 'AyurezeE2EETrackState(participant: $participantIdentity, '
      'track: $trackSid, kind: $kind, state: $state, secure: ${state.isSecure})';
}
