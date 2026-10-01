import 'package:ayureze_telehealth/ayureze_telehealth.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('AyurezeTelehealthClient guard rails', () {
    test('authenticate() before initialize() throws NotInitializedException', () async {
      final client = AyurezeTelehealthClient(apiBaseUrl: 'https://api.test', livekitUrl: 'wss://lk.test');
      await expectLater(
        client.authenticate(tenant: 't', email: 'e', password: 'p'),
        throwsA(isA<NotInitializedException>()),
      );
    });

    test('createSession() before authenticate() throws NotInitializedException', () async {
      final client = AyurezeTelehealthClient(apiBaseUrl: 'https://api.test', livekitUrl: 'wss://lk.test');
      await client.initialize();
      await expectLater(
        client.createSession(patientEmail: 'p@example.com'),
        throwsA(isA<NotInitializedException>()),
      );
    });

    test('enableMicrophone() before joinSession() throws ConnectionException', () async {
      final client = AyurezeTelehealthClient(apiBaseUrl: 'https://api.test', livekitUrl: 'wss://lk.test');
      await client.initialize();
      await expectLater(client.enableMicrophone(), throwsA(isA<ConnectionException>()));
    });

    test('getConnectionState() is disconnected before any join', () async {
      final client = AyurezeTelehealthClient(apiBaseUrl: 'https://api.test', livekitUrl: 'wss://lk.test');
      await client.initialize();
      expect(client.getConnectionState(), AyurezeConnectionState.disconnected);
    });

    test('getParticipants() is empty before any join', () async {
      final client = AyurezeTelehealthClient(apiBaseUrl: 'https://api.test', livekitUrl: 'wss://lk.test');
      await client.initialize();
      expect(client.getParticipants(), isEmpty);
    });

    test('getE2EETrackStates() is empty before any join', () async {
      final client = AyurezeTelehealthClient(apiBaseUrl: 'https://api.test', livekitUrl: 'wss://lk.test');
      await client.initialize();
      expect(client.getE2EETrackStates(), isEmpty);
    });

    test('getSessionState() is null before createSession/joinSession', () async {
      final client = AyurezeTelehealthClient(apiBaseUrl: 'https://api.test', livekitUrl: 'wss://lk.test');
      await client.initialize();
      expect(client.getSessionState(), isNull);
    });

    test('setLanguage()/preferredLanguage round-trips without requiring auth', () async {
      final client = AyurezeTelehealthClient(apiBaseUrl: 'https://api.test', livekitUrl: 'wss://lk.test');
      expect(client.preferredLanguage, 'en');
      client.setLanguage('ta');
      expect(client.preferredLanguage, 'ta');
    });
  });
}
