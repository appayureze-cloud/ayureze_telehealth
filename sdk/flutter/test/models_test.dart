import 'package:ayureze_telehealth/src/models/models.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('AyurezeCaption.fromJson', () {
    test('parses a normal (not blocked) caption', () {
      final caption = AyurezeCaption.fromJson({
        'speaker_identity': 'doctor-1',
        'source_lang': 'en',
        'target_lang': 'ta',
        'original_text': 'Take two tablets daily.',
        'translated_text': 'ஒரு நாளைக்கு இரண்டு மாத்திரைகள் எடுத்துக்கொள்ளுங்கள்.',
        'blocked': false,
        'timings_ms': {'stt_ms': 120.5, 'translation_ms': 300.0},
        'at': 1700000000.0,
      });

      expect(caption.speakerIdentity, 'doctor-1');
      expect(caption.sourceLanguage, 'en');
      expect(caption.targetLanguage, 'ta');
      expect(caption.blocked, isFalse);
      expect(caption.translatedText, isNotNull);
      expect(caption.timingsMs['stt_ms'], 120.5);
      expect(caption.at.millisecondsSinceEpoch, 1700000000000);
    });

    test('parses a safety-blocked caption with a null translated_text', () {
      final caption = AyurezeCaption.fromJson({
        'speaker_identity': 'patient-1',
        'source_lang': 'ta',
        'target_lang': 'en',
        'original_text': 'சில அறிகுறிகள்',
        'translated_text': null,
        'blocked': true,
        'timings_ms': <String, dynamic>{},
        'at': 1700000000.0,
      });

      expect(caption.blocked, isTrue);
      expect(caption.translatedText, isNull);
    });

    test('tolerates missing optional fields', () {
      final caption = AyurezeCaption.fromJson(const {});
      expect(caption.originalText, '');
      expect(caption.blocked, isFalse);
      expect(caption.timingsMs, isEmpty);
    });
  });

  group('role/status parsing helpers', () {
    test('userRoleFromString maps known + unknown values', () {
      expect(userRoleFromString('doctor'), AyurezeUserRole.doctor);
      expect(userRoleFromString('admin'), AyurezeUserRole.admin);
      expect(userRoleFromString('patient'), AyurezeUserRole.patient);
      expect(userRoleFromString('bogus'), AyurezeUserRole.patient);
    });

    test('sessionStatusFromString maps known + unknown values', () {
      expect(sessionStatusFromString('active'), AyurezeSessionStatus.active);
      expect(sessionStatusFromString('ended'), AyurezeSessionStatus.ended);
      expect(sessionStatusFromString('created'), AyurezeSessionStatus.created);
      expect(sessionStatusFromString('bogus'), AyurezeSessionStatus.created);
    });

    test('participantRoleFromAttribute maps known + unknown/null values', () {
      expect(participantRoleFromAttribute('doctor'), AyurezeParticipantRole.doctor);
      expect(participantRoleFromAttribute('patient'), AyurezeParticipantRole.patient);
      expect(participantRoleFromAttribute('ai_agent'), AyurezeParticipantRole.aiAgent);
      expect(participantRoleFromAttribute(null), AyurezeParticipantRole.unknown);
      expect(participantRoleFromAttribute('bogus'), AyurezeParticipantRole.unknown);
    });
  });
}
