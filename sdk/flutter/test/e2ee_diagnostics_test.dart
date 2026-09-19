import 'package:ayureze_telehealth/ayureze_telehealth.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('AyurezeE2EEState.isSecure — fail-closed classification', () {
    test('ok and keyRatcheted are secure', () {
      expect(AyurezeE2EEState.ok.isSecure, isTrue);
      expect(AyurezeE2EEState.keyRatcheted.isSecure, isTrue);
    });

    test('pending (not yet confirmed) is NOT secure', () {
      expect(AyurezeE2EEState.pending.isSecure, isFalse);
    });

    test('missingKey is NOT secure', () {
      expect(AyurezeE2EEState.missingKey.isSecure, isFalse);
    });

    test('decryptionFailed is NOT secure', () {
      expect(AyurezeE2EEState.decryptionFailed.isSecure, isFalse);
    });

    test('encryptionFailed is NOT secure', () {
      expect(AyurezeE2EEState.encryptionFailed.isSecure, isFalse);
    });

    test('internalError is NOT secure', () {
      expect(AyurezeE2EEState.internalError.isSecure, isFalse);
    });

    test('unknown (unrecognized) state is NOT secure', () {
      expect(AyurezeE2EEState.unknown.isSecure, isFalse);
    });
  });

  group('AyurezeE2EEDiagnostics — state recording and fail-closed reporting', () {
    late AyurezeE2EEDiagnostics diagnostics;

    setUp(() => diagnostics = AyurezeE2EEDiagnostics());
    tearDown(() => diagnostics.dispose());

    test('Case A — healthy encrypted track is reported as secure/usable', () {
      diagnostics.recordState(
        participantIdentity: 'doctor-1',
        isLocalParticipant: false,
        trackSid: 'TR_audio1',
        kind: AyurezeTrackKind.audio,
        state: AyurezeE2EEState.ok,
      );

      final states = diagnostics.all;
      expect(states, hasLength(1));
      expect(states.single.state, AyurezeE2EEState.ok);
      expect(states.single.state.isSecure, isTrue);
    });

    test('Case B — MissingKey is reported unsafe', () {
      diagnostics.recordState(
        participantIdentity: 'doctor-1',
        isLocalParticipant: false,
        trackSid: 'TR_audio1',
        kind: AyurezeTrackKind.audio,
        state: AyurezeE2EEState.missingKey,
      );

      expect(diagnostics.all.single.state.isSecure, isFalse);
    });

    test('Case C — DecryptionFailed is reported unsafe', () {
      diagnostics.recordState(
        participantIdentity: 'doctor-1',
        isLocalParticipant: false,
        trackSid: 'TR_audio1',
        kind: AyurezeTrackKind.audio,
        state: AyurezeE2EEState.decryptionFailed,
      );

      expect(diagnostics.all.single.state.isSecure, isFalse);
    });

    test('Case D — EncryptionFailed is reported unsafe', () {
      diagnostics.recordState(
        participantIdentity: 'patient-1',
        isLocalParticipant: true,
        trackSid: 'TR_audio_local',
        kind: AyurezeTrackKind.audio,
        state: AyurezeE2EEState.encryptionFailed,
      );

      expect(diagnostics.all.single.state.isSecure, isFalse);
    });

    test('Case E — unknown/unrecognized error is reported unsafe', () {
      diagnostics.recordState(
        participantIdentity: 'doctor-1',
        isLocalParticipant: false,
        trackSid: 'TR_video1',
        kind: AyurezeTrackKind.video,
        state: AyurezeE2EEState.unknown,
      );

      expect(diagnostics.all.single.state.isSecure, isFalse);
    });

    test('Case F — track removal clears that track\'s state', () {
      diagnostics.recordState(
        participantIdentity: 'doctor-1',
        isLocalParticipant: false,
        trackSid: 'TR_audio1',
        kind: AyurezeTrackKind.audio,
        state: AyurezeE2EEState.ok,
      );
      expect(diagnostics.all, hasLength(1));

      diagnostics.removeTrack('TR_audio1');
      expect(diagnostics.all, isEmpty);
    });

    test('removeTrack() for an unknown track sid is a no-op, not an error', () {
      expect(() => diagnostics.removeTrack('never-recorded'), returnsNormally);
      expect(diagnostics.all, isEmpty);
    });

    test('Case G — participant disconnect clears every track of theirs, and only theirs', () {
      diagnostics.recordState(
        participantIdentity: 'doctor-1',
        isLocalParticipant: false,
        trackSid: 'TR_doctor_audio',
        kind: AyurezeTrackKind.audio,
        state: AyurezeE2EEState.ok,
      );
      diagnostics.recordState(
        participantIdentity: 'doctor-1',
        isLocalParticipant: false,
        trackSid: 'TR_doctor_video',
        kind: AyurezeTrackKind.video,
        state: AyurezeE2EEState.ok,
      );
      diagnostics.recordState(
        participantIdentity: 'patient-1',
        isLocalParticipant: true,
        trackSid: 'TR_patient_audio',
        kind: AyurezeTrackKind.audio,
        state: AyurezeE2EEState.ok,
      );

      diagnostics.removeParticipant('doctor-1');

      final remaining = diagnostics.all;
      expect(remaining, hasLength(1));
      expect(remaining.single.participantIdentity, 'patient-1');
    });

    test('multiple participants, multiple tracks each, are tracked independently', () {
      diagnostics.recordState(
        participantIdentity: 'doctor-1',
        isLocalParticipant: false,
        trackSid: 'TR_a',
        kind: AyurezeTrackKind.audio,
        state: AyurezeE2EEState.ok,
      );
      diagnostics.recordState(
        participantIdentity: 'doctor-1',
        isLocalParticipant: false,
        trackSid: 'TR_b',
        kind: AyurezeTrackKind.video,
        state: AyurezeE2EEState.missingKey,
      );
      diagnostics.recordState(
        participantIdentity: 'ai-agent-1',
        isLocalParticipant: false,
        trackSid: 'TR_c',
        kind: AyurezeTrackKind.audio,
        state: AyurezeE2EEState.decryptionFailed,
      );

      expect(diagnostics.all, hasLength(3));
      final bySid = {for (final s in diagnostics.all) s.trackSid: s};
      expect(bySid['TR_a']!.state.isSecure, isTrue);
      expect(bySid['TR_b']!.state.isSecure, isFalse);
      expect(bySid['TR_c']!.state.isSecure, isFalse);
    });

    test('state transitions: a track going from ok to decryptionFailed is reflected, not stuck healthy', () {
      diagnostics.recordState(
        participantIdentity: 'doctor-1',
        isLocalParticipant: false,
        trackSid: 'TR_audio1',
        kind: AyurezeTrackKind.audio,
        state: AyurezeE2EEState.ok,
      );
      expect(diagnostics.all.single.state.isSecure, isTrue);

      diagnostics.recordState(
        participantIdentity: 'doctor-1',
        isLocalParticipant: false,
        trackSid: 'TR_audio1',
        kind: AyurezeTrackKind.audio,
        state: AyurezeE2EEState.decryptionFailed,
      );

      final states = diagnostics.all;
      expect(states, hasLength(1), reason: 'same trackSid overwrites, not duplicates');
      expect(states.single.state, AyurezeE2EEState.decryptionFailed);
      expect(states.single.state.isSecure, isFalse);
    });

    test('a track is never silently marked healthy again without an explicit ok/keyRatcheted event', () {
      diagnostics.recordState(
        participantIdentity: 'doctor-1',
        isLocalParticipant: false,
        trackSid: 'TR_audio1',
        kind: AyurezeTrackKind.audio,
        state: AyurezeE2EEState.missingKey,
      );
      // No further event arrives — state must remain exactly what LiveKit
      // last reported, not silently reset to ok/secure.
      expect(diagnostics.all.single.state, AyurezeE2EEState.missingKey);
      expect(diagnostics.all.single.state.isSecure, isFalse);
    });

    test('room-level clear() removes all state regardless of participant/track', () {
      diagnostics.recordState(
        participantIdentity: 'doctor-1',
        isLocalParticipant: false,
        trackSid: 'TR_a',
        kind: AyurezeTrackKind.audio,
        state: AyurezeE2EEState.ok,
      );
      diagnostics.recordState(
        participantIdentity: 'patient-1',
        isLocalParticipant: true,
        trackSid: 'TR_b',
        kind: AyurezeTrackKind.video,
        state: AyurezeE2EEState.ok,
      );

      diagnostics.clear();

      expect(diagnostics.all, isEmpty);
    });

    test('stateChanges stream emits every recorded state, in order', () async {
      final events = <AyurezeE2EETrackState>[];
      final sub = diagnostics.stateChanges.listen(events.add);

      diagnostics.recordState(
        participantIdentity: 'doctor-1',
        isLocalParticipant: false,
        trackSid: 'TR_a',
        kind: AyurezeTrackKind.audio,
        state: AyurezeE2EEState.pending,
      );
      diagnostics.recordState(
        participantIdentity: 'doctor-1',
        isLocalParticipant: false,
        trackSid: 'TR_a',
        kind: AyurezeTrackKind.audio,
        state: AyurezeE2EEState.ok,
      );

      await Future<void>.delayed(Duration.zero);
      await sub.cancel();

      expect(events.map((e) => e.state), [AyurezeE2EEState.pending, AyurezeE2EEState.ok]);
    });

    test('dispose() closes the stream and clears state; recordState() after dispose does not throw', () async {
      diagnostics.recordState(
        participantIdentity: 'doctor-1',
        isLocalParticipant: false,
        trackSid: 'TR_a',
        kind: AyurezeTrackKind.audio,
        state: AyurezeE2EEState.ok,
      );

      await diagnostics.dispose();

      expect(diagnostics.all, isEmpty);
      expect(
        () => diagnostics.recordState(
          participantIdentity: 'doctor-1',
          isLocalParticipant: false,
          trackSid: 'TR_a',
          kind: AyurezeTrackKind.audio,
          state: AyurezeE2EEState.ok,
        ),
        returnsNormally,
      );
    });
  });

  group('AyurezeE2EETrackState — no sensitive material in its public surface', () {
    test('toString() and field set never include key/token/media-shaped data', () {
      final state = AyurezeE2EETrackState(
        participantIdentity: 'doctor-1',
        isLocalParticipant: false,
        trackSid: 'TR_audio1',
        kind: AyurezeTrackKind.audio,
        state: AyurezeE2EEState.decryptionFailed,
        at: DateTime.utc(2026, 1, 1),
      );

      // The type's entire public surface is participant identity, track
      // sid, kind, state, and timestamp — there is no field a key, token,
      // or media buffer could even be assigned to. toString() must not
      // introduce one either.
      final rendered = state.toString();
      expect(rendered, contains('doctor-1'));
      expect(rendered, contains('TR_audio1'));
      expect(rendered, contains('decryptionFailed'));
      expect(rendered, isNot(contains('key')));
      expect(rendered, isNot(contains('token')));
    });
  });
}
