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
