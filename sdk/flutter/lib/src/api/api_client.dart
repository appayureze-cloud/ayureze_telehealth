import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:meta/meta.dart';

import '../exceptions.dart';
import '../models/models.dart';

/// Thin, directly-testable wrapper around the Go API's authenticated
/// endpoints (see docs/api/README.md). [AyurezeTelehealthClient] is the
/// public-facing headless API; this class is what it delegates HTTP calls
/// to, kept separate so it can be unit tested with a fake [http.Client]
/// without needing LiveKit or a device.
class ApiClient {
  final String baseUrl;
  final http.Client _http;

  ApiClient({required this.baseUrl, http.Client? httpClient}) : _http = httpClient ?? http.Client();

  Uri _uri(String path) => Uri.parse('$baseUrl$path');

  Map<String, String> _authHeaders(String accessToken) => {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer $accessToken',
      };

  Future<Map<String, dynamic>> _decodeOrThrow(http.Response resp) async {
    final body = resp.body.isEmpty ? <String, dynamic>{} : jsonDecode(resp.body) as Map<String, dynamic>;
    if (resp.statusCode >= 200 && resp.statusCode < 300) {
      return body;
    }
    throw ApiException(
      resp.statusCode,
      body['error'] as String? ?? 'unknown_error',
      body['message'] as String? ?? 'request failed with status ${resp.statusCode}',
    );
  }

  Future<AuthResult> login({required String tenant, required String email, required String password}) async {
    final resp = await _http.post(
      _uri('/v1/auth/login'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'tenant': tenant, 'email': email, 'password': password}),
    );
    final json = await _decodeOrThrow(resp);
    return AuthResult.fromJson(json);
  }

  Future<AuthResult> refresh(String refreshToken) async {
    final resp = await _http.post(
      _uri('/v1/auth/refresh'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'refresh_token': refreshToken}),
    );
    final json = await _decodeOrThrow(resp);
    return AuthResult.fromJson(json);
  }

  Future<void> logout(String refreshToken) async {
    await _http.post(
      _uri('/v1/auth/logout'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'refresh_token': refreshToken}),
    );
  }

  Future<AyurezeSessionState> createSession({
    required String accessToken,
    required String patientEmail,
  }) async {
    final resp = await _http.post(
      _uri('/v1/sessions'),
      headers: _authHeaders(accessToken),
      body: jsonEncode({'patient_email': patientEmail}),
    );
    final json = await _decodeOrThrow(resp);
    return _sessionFromJson(json);
  }

  Future<JoinResult> joinSession({required String accessToken, required String sessionId}) async {
    final resp = await _http.post(
      _uri('/v1/sessions/$sessionId/join'),
      headers: _authHeaders(accessToken),
    );
    final json = await _decodeOrThrow(resp);
    return JoinResult(
      livekitAccessToken: json['access_token'] as String,
      room: json['room'] as String,
      e2eeKeyBase64: json['e2ee_key'] as String,
      session: _sessionFromJson(json['session'] as Map<String, dynamic>),
    );
  }

  Future<AyurezeSessionState> endSession({required String accessToken, required String sessionId}) async {
    final resp = await _http.post(
      _uri('/v1/sessions/$sessionId/end'),
      headers: _authHeaders(accessToken),
    );
    final json = await _decodeOrThrow(resp);
    return _sessionFromJson(json);
  }

  Future<AyurezeSessionState> getSession({required String accessToken, required String sessionId}) async {
    final resp = await _http.get(
      _uri('/v1/sessions/$sessionId'),
      headers: _authHeaders(accessToken),
    );
    final json = await _decodeOrThrow(resp);
    return _sessionFromJson(json);
  }

  Future<void> grantAiTranslationConsent({required String accessToken, required String sessionId}) async {
    final resp = await _http.post(
      _uri('/v1/sessions/$sessionId/consent/ai-translation/grant'),
      headers: _authHeaders(accessToken),
    );
    await _decodeOrThrow(resp);
  }

  Future<void> revokeAiTranslationConsent({required String accessToken, required String sessionId}) async {
    final resp = await _http.post(
      _uri('/v1/sessions/$sessionId/consent/ai-translation/revoke'),
      headers: _authHeaders(accessToken),
    );
    await _decodeOrThrow(resp);
  }

  AyurezeSessionState _sessionFromJson(Map<String, dynamic> json) => AyurezeSessionState(
        id: json['id'] as String,
        room: json['room'] as String,
        status: sessionStatusFromString(json['status'] as String? ?? 'created'),
        aiTranslationAuthorized: json['ai_translation_authorized'] as bool? ?? false,
      );

  @visibleForTesting
  void close() => _http.close();
}

class AuthResult {
  final String accessToken;
  final String refreshToken;
  final DateTime expiresAt;
  final AyurezeUser user;

  const AuthResult({
    required this.accessToken,
    required this.refreshToken,
    required this.expiresAt,
    required this.user,
  });

  factory AuthResult.fromJson(Map<String, dynamic> json) {
    final userJson = json['user'] as Map<String, dynamic>;
    return AuthResult(
      accessToken: json['access_token'] as String,
      refreshToken: json['refresh_token'] as String,
      expiresAt: DateTime.parse(json['expires_at'] as String),
      user: AyurezeUser(
        id: userJson['id'] as String,
        email: userJson['email'] as String,
        role: userRoleFromString(userJson['role'] as String? ?? 'patient'),
        displayName: userJson['display_name'] as String? ?? '',
      ),
    );
  }
}

class JoinResult {
  final String livekitAccessToken;
  final String room;
  final String e2eeKeyBase64;
  final AyurezeSessionState session;

  const JoinResult({
    required this.livekitAccessToken,
    required this.room,
    required this.e2eeKeyBase64,
    required this.session,
  });
}
