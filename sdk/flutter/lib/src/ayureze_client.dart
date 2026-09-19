import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:livekit_client/livekit_client.dart' as lk;

import 'api/api_client.dart';
import 'exceptions.dart';
import 'models/models.dart';

export 'api/api_client.dart' show AuthResult, JoinResult;
export 'exceptions.dart';
export 'models/models.dart';

const _captionsTopic = 'ayureze.captions';

/// Headless client for the AyurEze Telehealth platform. Wraps the Go
/// session API (auth, session lifecycle, consent) and the LiveKit Flutter
/// client (encrypted media) behind a single, LiveKit-agnostic surface, so
/// the AyurEze Patient/Doctor apps build their own UI without depending on
/// either's internals directly.
///
/// Typical usage:
/// ```dart
/// final client = AyurezeTelehealthClient(
///   apiBaseUrl: 'https://api.ayureze.example',
///   livekitUrl: 'wss://livekit.ayureze.example',
/// );
/// await client.initialize();
/// await client.authenticate(tenant: 'clinic-1', email: 'doctor@clinic.example', password: '...');
/// final session = await client.createSession(patientEmail: 'patient@example.com');
/// await client.joinSession(session.id);
/// await client.enableMicrophone();
/// await client.enableCamera();
/// ```
class AyurezeTelehealthClient {
  final ApiClient _api;
  final String _livekitUrl;

  bool _initialized = false;
  AuthResult? _auth;
  AyurezeSessionState? _sessionState;
  lk.Room? _room;
  lk.EventsListener<lk.RoomEvent>? _roomListener;
  String _preferredLanguage = 'en';

  final StreamController<AyurezeCaption> _captionsController = StreamController<AyurezeCaption>.broadcast();
  final StreamController<AyurezeConnectionState> _connectionStateController =
      StreamController<AyurezeConnectionState>.broadcast();

  AyurezeTelehealthClient({
    required String apiBaseUrl,
    required String livekitUrl,
    http.Client? httpClient,
  })  : _api = ApiClient(baseUrl: apiBaseUrl, httpClient: httpClient),
        _livekitUrl = livekitUrl;

  /// Live stream of translated/original captions from the AI translation
  /// agent, when AI translation is enabled (see [enableAITranslation]).
  /// Empty (no events) in Private Mode.
  Stream<AyurezeCaption> get captions => _captionsController.stream;

  /// Live stream of LiveKit connection state changes. Also queryable
  /// synchronously via [getConnectionState].
  Stream<AyurezeConnectionState> get connectionStateChanges => _connectionStateController.stream;

  // ---------------------------------------------------------------------
  // Lifecycle
  // ---------------------------------------------------------------------

  /// Must be called once before any other method. Currently a no-op
  /// beyond marking the client ready — kept as an explicit step so a
  /// future version can do async setup (e.g. platform capability checks)
  /// without changing the public API.
  Future<void> initialize() async {
    _initialized = true;
  }

  /// Logs in against the Go API and stores the resulting access/refresh
  /// tokens for subsequent calls. Must be called before
  /// [createSession]/[joinSession]/etc.
  Future<AyurezeUser> authenticate({
    required String tenant,
    required String email,
    required String password,
  }) async {
    _ensureInitialized();
    final result = await _api.login(tenant: tenant, email: email, password: password);
    _auth = result;
    return result.user;
  }

  // ---------------------------------------------------------------------
  // Session lifecycle
  // ---------------------------------------------------------------------

  /// Creates a new session (doctor/admin only — the Go API enforces this;
  /// see docs/security/README.md). [patientEmail] must belong to a patient
  /// in the caller's own tenant.
  Future<AyurezeSessionState> createSession({required String patientEmail}) async {
    final auth = _ensureAuthenticated();
    final session = await _api.createSession(accessToken: auth.accessToken, patientEmail: patientEmail);
    _sessionState = session;
    return session;
  }

  /// Joins [sessionId]'s encrypted LiveKit room. Only the session's own
  /// doctor/patient (or an admin) may succeed — see
  /// docs/security/README.md. Applies the session's real E2EE key
  /// (delivered only in this call's response) before connecting, so
  /// LiveKit's SFrame encryption is active from the first published
  /// frame.
  Future<AyurezeSessionState> joinSession(String sessionId) async {
    final auth = _ensureAuthenticated();
    final joinResult = await _api.joinSession(accessToken: auth.accessToken, sessionId: sessionId);
    _sessionState = joinResult.session;

    final keyProvider = await lk.BaseKeyProvider.create();
    // IMPORTANT: pass the base64 *text* straight through, do NOT
    // base64-decode it first. livekit_client's setSharedKey(String) takes
    // the string's UTF-16 code units as the raw key bytes
    // (`Uint8List.fromList(key.codeUnits)`) and hands them to the native
    // KeyProvider, which runs its default PBKDF2 (salt
    // "LKFrameEncryptionKey", 100000 iterations, SHA-256) over them. The
    // Web SDK's ExternalE2EEKeyProvider.setKey(String) UTF-8-encodes this
    // same base64 text and runs the identical PBKDF2 over it — for pure
    // ASCII text (which base64 always is), UTF-16 code units and UTF-8
    // bytes are identical, so both platforms derive the same key only if
    // both feed in the base64 *text*. Decoding to raw bytes first derives
    // a different, incompatible key (see docs/e2ee/VALIDATION.md's
    // key-derivation-input finding).
    await keyProvider.setSharedKey(joinResult.e2eeKeyBase64);

    final room = lk.Room(
      roomOptions: lk.RoomOptions(
        e2eeOptions: lk.E2EEOptions(keyProvider: keyProvider),
        adaptiveStream: true,
        dynacast: true,
      ),
    );
    _room = room;
    _wireRoomListeners(room);

    try {
      await room.connect(_livekitUrl, joinResult.livekitAccessToken);
    } catch (e) {
      _room = null;
      throw ConnectionException('failed to connect to LiveKit room: $e');
    }

    return joinResult.session;
  }

  /// Disconnects from the current session's room without ending the
  /// session itself (the other participant can remain connected). Safe
  /// to call even if not currently joined.
  Future<void> leaveSession() async {
    await _roomListener?.dispose();
    _roomListener = null;
    await _room?.disconnect();
    _room = null;
    _connectionStateController.add(AyurezeConnectionState.disconnected);
  }

  /// Ends the session entirely (doctor/admin only) — the Go API deletes
  /// the LiveKit room, disconnecting every participant including the AI
  /// agent if present.
  Future<AyurezeSessionState> endSession() async {
    final auth = _ensureAuthenticated();
    final sessionId = _ensureSessionId();
    final session = await _api.endSession(accessToken: auth.accessToken, sessionId: sessionId);
    _sessionState = session;
    return session;
  }

  // ---------------------------------------------------------------------
  // Media controls
  // ---------------------------------------------------------------------

  // These are `async` (rather than `=>` arrow functions) specifically so
  // that _ensureRoom()'s throw when not yet connected surfaces through
  // the returned Future's error channel, not as a synchronous throw at
  // call time — callers should be able to uniformly `await` and `catch`
  // every method on this client.

  Future<void> enableMicrophone() async {
    await _ensureRoom().localParticipant?.setMicrophoneEnabled(true);
  }

  Future<void> disableMicrophone() async {
    await _ensureRoom().localParticipant?.setMicrophoneEnabled(false);
  }

  Future<void> enableCamera() async {
    await _ensureRoom().localParticipant?.setCameraEnabled(true);
  }

  Future<void> disableCamera() async {
    await _ensureRoom().localParticipant?.setCameraEnabled(false);
  }

  // ---------------------------------------------------------------------
  // AI translation (Mode B — see docs/e2ee/README.md)
  // ---------------------------------------------------------------------

  /// Grants AI-translation consent for the current session. This alone
  /// does not make the AI agent join — it only makes the agent's own
  /// authorization check (Go API, consent-gated) succeed the next time
  /// it's triggered. The platform never activates AI translation without
  /// this explicit call from a session participant.
  Future<void> enableAITranslation() async {
    final auth = _ensureAuthenticated();
    final sessionId = _ensureSessionId();
    await _api.grantAiTranslationConsent(accessToken: auth.accessToken, sessionId: sessionId);
  }

  /// Revokes AI-translation consent. The Go API immediately force-removes
  /// the AI agent from the room if it's currently connected — this call
  /// returning does not mean the removal has necessarily completed on the
  /// LiveKit side yet, but it has been requested synchronously as part of
  /// the same API call.
  Future<void> disableAITranslation() async {
    final auth = _ensureAuthenticated();
    final sessionId = _ensureSessionId();
    await _api.revokeAiTranslationConsent(accessToken: auth.accessToken, sessionId: sessionId);
  }

  /// Sets the caller's preferred spoken/caption language (an ISO 639-1
  /// code, e.g. `"en"`, `"ta"`, `"ml"`). Informational for the SDK's own
  /// caption stream today — future versions may use this to filter
  /// [captions] or otherwise localize.
  void setLanguage(String languageCode) {
    _preferredLanguage = languageCode;
  }

  String get preferredLanguage => _preferredLanguage;

  // ---------------------------------------------------------------------
  // State queries
  // ---------------------------------------------------------------------

  AyurezeConnectionState getConnectionState() {
    final room = _room;
    if (room == null) return AyurezeConnectionState.disconnected;
    return _mapConnectionState(room.connectionState);
  }

  List<AyurezeParticipant> getParticipants() {
    final room = _room;
    if (room == null) return const [];

    final result = <AyurezeParticipant>[];
    final local = room.localParticipant;
    if (local != null) {
      result.add(_toAyurezeParticipant(local, isLocal: true));
    }
    for (final p in room.remoteParticipants.values) {
      result.add(_toAyurezeParticipant(p, isLocal: false));
    }
    return result;
  }

  AyurezeSessionState? getSessionState() => _sessionState;

  // ---------------------------------------------------------------------
  // Internals
  // ---------------------------------------------------------------------

  void _wireRoomListeners(lk.Room room) {
    final listener = room.createListener();
    _roomListener = listener;

    listener
      ..on<lk.RoomConnectedEvent>((_) => _connectionStateController.add(AyurezeConnectionState.connected))
      ..on<lk.RoomReconnectingEvent>((_) => _connectionStateController.add(AyurezeConnectionState.reconnecting))
      ..on<lk.RoomReconnectedEvent>((_) => _connectionStateController.add(AyurezeConnectionState.connected))
      ..on<lk.RoomDisconnectedEvent>((_) => _connectionStateController.add(AyurezeConnectionState.disconnected))
      ..on<lk.DataReceivedEvent>((event) {
        if (event.topic != _captionsTopic) return;
        try {
          final json = jsonDecode(utf8.decode(event.data)) as Map<String, dynamic>;
          _captionsController.add(AyurezeCaption.fromJson(json));
        } catch (_) {
          // Malformed caption payload — drop it rather than crash the
          // caller's stream subscription.
        }
      });
  }

  AyurezeParticipant _toAyurezeParticipant(lk.Participant p, {required bool isLocal}) {
    return AyurezeParticipant(
      identity: p.identity,
      role: participantRoleFromAttribute(p.attributes['role']),
      audioEnabled: p.isMicrophoneEnabled(),
      videoEnabled: p.isCameraEnabled(),
      isLocal: isLocal,
    );
  }

  AyurezeConnectionState _mapConnectionState(lk.ConnectionState state) => switch (state) {
        lk.ConnectionState.connected => AyurezeConnectionState.connected,
        lk.ConnectionState.connecting => AyurezeConnectionState.connecting,
        lk.ConnectionState.reconnecting => AyurezeConnectionState.reconnecting,
        lk.ConnectionState.disconnected => AyurezeConnectionState.disconnected,
      };

  void _ensureInitialized() {
    if (!_initialized) {
      throw const NotInitializedException('call initialize() before using the client');
    }
  }

  AuthResult _ensureAuthenticated() {
    _ensureInitialized();
    final auth = _auth;
    if (auth == null) {
      throw const NotInitializedException('call authenticate() before this method');
    }
    return auth;
  }

  String _ensureSessionId() {
    final id = _sessionState?.id;
    if (id == null) {
      throw const NotInitializedException('no active session — call createSession() or joinSession() first');
    }
    return id;
  }

  lk.Room _ensureRoom() {
    final room = _room;
    if (room == null) {
      throw const ConnectionException('not connected to a session — call joinSession() first');
    }
    return room;
  }

  /// Releases all resources (room connection, stream controllers). Call
  /// when the client is no longer needed (e.g. app/screen disposal).
  Future<void> dispose() async {
    await leaveSession();
    await _captionsController.close();
    await _connectionStateController.close();
  }
}
