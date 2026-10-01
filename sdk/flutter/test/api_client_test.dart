import 'dart:async';
import 'dart:convert';

import 'package:ayureze_telehealth/src/api/api_client.dart';
import 'package:ayureze_telehealth/src/exceptions.dart';
import 'package:ayureze_telehealth/src/models/models.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:flutter_test/flutter_test.dart';

http.Client _fakeClient(FutureOr<http.Response> Function(http.Request) handler) {
  return MockClient((request) async => handler(request));
}

void main() {
  group('ApiClient.login', () {
    test('sends tenant/email/password and parses a successful response', () async {
      http.Request? captured;
      final client = ApiClient(
        baseUrl: 'https://api.test',
        httpClient: _fakeClient((req) {
          captured = req;
          return http.Response(
            jsonEncode({
              'access_token': 'access-123',
              'refresh_token': 'refresh-456',
              'expires_at': '2030-01-01T00:00:00Z',
              'user': {
                'id': 'user-1',
                'email': 'doctor@example.com',
                'role': 'doctor',
                'display_name': 'Dr. Test',
              },
            }),
            200,
          );
        }),
      );

      final result = await client.login(tenant: 'clinic-1', email: 'doctor@example.com', password: 'secret');

      expect(captured!.url.toString(), 'https://api.test/v1/auth/login');
      final sentBody = jsonDecode(captured!.body) as Map<String, dynamic>;
      expect(sentBody['tenant'], 'clinic-1');
      expect(sentBody['email'], 'doctor@example.com');
      expect(sentBody['password'], 'secret');

      expect(result.accessToken, 'access-123');
      expect(result.refreshToken, 'refresh-456');
      expect(result.user.role, AyurezeUserRole.doctor);
      expect(result.user.displayName, 'Dr. Test');
    });

    test('throws ApiException with the error code/message on 401', () async {
      final client = ApiClient(
        baseUrl: 'https://api.test',
        httpClient: _fakeClient((_) => http.Response(
              jsonEncode({'error': 'unauthorized', 'message': 'invalid credentials'}),
              401,
            )),
      );

      await expectLater(
        client.login(tenant: 'clinic-1', email: 'x@example.com', password: 'wrong'),
        throwsA(
          isA<ApiException>()
              .having((e) => e.statusCode, 'statusCode', 401)
              .having((e) => e.errorCode, 'errorCode', 'unauthorized')
              .having((e) => e.message, 'message', 'invalid credentials'),
        ),
      );
    });
  });

  group('ApiClient.joinSession', () {
    test('parses access token, room, e2ee key, and nested session', () async {
      final client = ApiClient(
        baseUrl: 'https://api.test',
        httpClient: _fakeClient((req) {
          expect(req.url.path, '/v1/sessions/session-1/join');
          expect(req.headers['Authorization'], 'Bearer token-abc');
          return http.Response(
            jsonEncode({
              'access_token': 'lk-token',
              'room': 'session-room-1',
              'e2ee_key': 'base64key==',
              'expires_at': '2030-01-01T00:00:00Z',
              'session': {
                'id': 'session-1',
                'room': 'session-room-1',
                'status': 'active',
                'ai_translation_authorized': false,
              },
            }),
            200,
          );
        }),
      );

      final result = await client.joinSession(accessToken: 'token-abc', sessionId: 'session-1');

      expect(result.livekitAccessToken, 'lk-token');
      expect(result.room, 'session-room-1');
      expect(result.e2eeKeyBase64, 'base64key==');
      expect(result.session.status, AyurezeSessionStatus.active);
    });
  });

  group('ApiClient consent endpoints', () {
    test('grantAiTranslationConsent posts to the grant endpoint', () async {
      String? calledPath;
      final client = ApiClient(
        baseUrl: 'https://api.test',
        httpClient: _fakeClient((req) {
          calledPath = req.url.path;
          return http.Response(jsonEncode({'status': 'granted'}), 200);
        }),
      );

      await client.grantAiTranslationConsent(accessToken: 't', sessionId: 's1');
      expect(calledPath, '/v1/sessions/s1/consent/ai-translation/grant');
    });

    test('revokeAiTranslationConsent posts to the revoke endpoint', () async {
      String? calledPath;
      final client = ApiClient(
        baseUrl: 'https://api.test',
        httpClient: _fakeClient((req) {
          calledPath = req.url.path;
          return http.Response(jsonEncode({'status': 'revoked'}), 200);
        }),
      );

      await client.revokeAiTranslationConsent(accessToken: 't', sessionId: 's1');
      expect(calledPath, '/v1/sessions/s1/consent/ai-translation/revoke');
    });
  });
}
