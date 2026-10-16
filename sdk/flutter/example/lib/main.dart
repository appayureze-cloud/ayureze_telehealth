// External Flutter E2EE interoperability test harness. Exercises the real
// ayureze_telehealth package exactly as a production app would — no second
// E2EE implementation, no shortcuts around AyurezeTelehealthClient. Built
// so a human tester with a real Android device/emulator can run Tests A/B/C
// from sdk/flutter/README.md's "External E2EE device test harness" section
// and read the live E2EE diagnostic state directly off the screen.
//
// SAFETY: this screen never displays an E2EE key, access token, ciphertext,
// or patient data — only what AyurezeE2EETrackState/AyurezeParticipant
// already expose (identifiers + state), plus this harness's own synthetic
// tenant/email/password test credentials the tester types in themselves.
// Use only against a synthetic/dev tenant — never real patient sessions.

import 'dart:async';

import 'package:ayureze_telehealth/ayureze_telehealth.dart';
import 'package:flutter/material.dart';

void main() => runApp(const E2EETestHarnessApp());

class E2EETestHarnessApp extends StatelessWidget {
  const E2EETestHarnessApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'AyurEze E2EE Test Harness',
      theme: ThemeData(colorSchemeSeed: Colors.teal, useMaterial3: true),
      home: const HarnessPage(),
    );
  }
}

class HarnessPage extends StatefulWidget {
  const HarnessPage({super.key});

  @override
  State<HarnessPage> createState() => _HarnessPageState();
}

class _HarnessPageState extends State<HarnessPage> {
  // Defaults match this repo's real dev-stack config (docker-compose,
  // infrastructure/docker/docker-compose.yml) — override in the fields
  // below for a device/emulator that can't reach "localhost" directly
  // (an Android emulator reaches the host machine at 10.0.2.2; a real
  // device needs the host's real LAN IP — see the README's "Network
  // requirements" section).
  final _apiUrlCtrl = TextEditingController(text: 'http://10.0.2.2:8080');
  final _livekitUrlCtrl = TextEditingController(text: 'ws://10.0.2.2:7880');
  final _tenantCtrl = TextEditingController(text: 'e2ee-harness-tenant');
  final _emailCtrl = TextEditingController(text: 'doctor@e2ee-harness.local');
  final _passwordCtrl = TextEditingController(text: 'dev-password-only-12345');
  final _sessionIdCtrl = TextEditingController();

  AyurezeTelehealthClient? _client;
  StreamSubscription<AyurezeConnectionState>? _connectionSub;
  StreamSubscription<AyurezeE2EETrackState>? _e2eeSub;

  AyurezeConnectionState _connectionState = AyurezeConnectionState.disconnected;
  List<AyurezeE2EETrackState> _trackStates = const [];
  List<AyurezeParticipant> _participants = const [];
  String? _lastSessionId;
  bool _micEnabled = false;
  Timer? _refreshTimer;

  final List<String> _log = [];

  void _appendLog(String line) {
    final ts = DateTime.now().toIso8601String().substring(11, 19);
    setState(() => _log.insert(0, '[$ts] $line'));
  }

  Future<void> _ensureClient() async {
    if (_client != null) return;
    final client = AyurezeTelehealthClient(
      apiBaseUrl: _apiUrlCtrl.text.trim(),
      livekitUrl: _livekitUrlCtrl.text.trim(),
    );
    await client.initialize();
    _client = client;

    _connectionSub = client.connectionStateChanges.listen((s) {
      setState(() => _connectionState = s);
      _appendLog('connection_state_changed state=${s.name}');
    });

    // The core diagnostic this harness exists to exercise. Every state
    // AyurezeE2EEDiagnostics records is safe to log/display as-is — see
    // AyurezeE2EETrackState's doc comment.
    _e2eeSub = client.e2eeStateChanges.listen((s) {
      setState(() => _trackStates = client.getE2EETrackStates());
      final tag = s.state.isSecure ? 'e2ee_state_changed' : 'e2ee_state_changed_unsafe';
      _appendLog(
        '$tag participant=${s.participantIdentity} local=${s.isLocalParticipant} '
        'track=${s.trackSid} kind=${s.kind.name} state=${s.state.name} secure=${s.state.isSecure}',
      );
    });

    // getParticipants() has no dedicated change stream today — poll it on
    // a slow interval purely for this harness's on-screen display; do not
    // copy this pattern into a real app's hot path.
    _refreshTimer = Timer.periodic(const Duration(seconds: 2), (_) {
      final c = _client;
      if (c == null) return;
      setState(() => _participants = c.getParticipants());
    });
  }

  Future<void> _authenticate() async {
    try {
      await _ensureClient();
      final user = await _client!.authenticate(
        tenant: _tenantCtrl.text.trim(),
        email: _emailCtrl.text.trim(),
        password: _passwordCtrl.text.trim(),
      );
      _appendLog('authenticated identity=${user.id} role=${user.role.name}');
    } catch (e) {
      _appendLog('ERROR authenticate: $e');
    }
  }

  /// Test B / Test C (first instance): create a session and join as its
  /// author, then publish audio — this side is the "Flutter" half of
  /// "Flutter -> Web" or "Flutter -> Flutter".
  Future<void> _createAndJoin() async {
    try {
      final patientEmail = 'patient@e2ee-harness.local';
      final session = await _client!.createSession(patientEmail: patientEmail);
      _appendLog('session created id=${session.id}');
      await _client!.joinSession(session.id);
      _lastSessionId = session.id;
      setState(() {});
      _appendLog('joined session id=${session.id} — give this id to the other side for Test A/C');
      await _client!.enableMicrophone();
      setState(() => _micEnabled = true);
      _appendLog('microphone enabled — publishing encrypted audio');
    } catch (e) {
      _appendLog('ERROR createAndJoin: $e');
    }
  }

  /// Test A / Test C (second instance): join a session another side
  /// already created (by session id) — this side is the "Flutter" half
  /// of "Web -> Flutter" (subscribe only) or "Flutter -> Flutter" (may
  /// also publish via the mic toggle below).
  Future<void> _joinExisting() async {
    try {
      final sessionId = _sessionIdCtrl.text.trim();
      if (sessionId.isEmpty) {
        _appendLog('ERROR joinExisting: enter the session id from the other side first');
        return;
      }
      await _client!.joinSession(sessionId);
      _lastSessionId = sessionId;
      setState(() {});
      _appendLog('joined session id=$sessionId');
    } catch (e) {
      _appendLog('ERROR joinExisting: $e');
    }
  }

  Future<void> _toggleMic() async {
    try {
      if (_micEnabled) {
        await _client!.disableMicrophone();
        setState(() => _micEnabled = false);
        _appendLog('microphone disabled');
      } else {
        await _client!.enableMicrophone();
        setState(() => _micEnabled = true);
        _appendLog('microphone enabled — publishing encrypted audio');
      }
    } catch (e) {
      _appendLog('ERROR toggleMic: $e');
    }
  }

  Future<void> _leave() async {
    try {
      await _client?.leaveSession();
      setState(() {
        _trackStates = const [];
        _participants = const [];
        _micEnabled = false;
      });
      _appendLog('left session');
    } catch (e) {
      _appendLog('ERROR leave: $e');
    }
  }

  @override
  void dispose() {
    _connectionSub?.cancel();
    _e2eeSub?.cancel();
    _refreshTimer?.cancel();
    _client?.dispose();
    for (final c in [_apiUrlCtrl, _livekitUrlCtrl, _tenantCtrl, _emailCtrl, _passwordCtrl, _sessionIdCtrl]) {
      c.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('AyurEze E2EE Test Harness')),
      body: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _configSection(),
            const SizedBox(height: 8),
            _actionsSection(),
            const SizedBox(height: 8),
            _statusSection(),
            const SizedBox(height: 8),
            Expanded(child: _e2eeStatesSection()),
            const SizedBox(height: 8),
            Expanded(child: _logSection()),
          ],
        ),
      ),
    );
  }

  Widget _configSection() {
    return ExpansionTile(
      title: const Text('Configuration'),
      initiallyExpanded: _client == null,
      children: [
        _field('API base URL', _apiUrlCtrl),
        _field('LiveKit URL', _livekitUrlCtrl),
        _field('Tenant', _tenantCtrl),
        _field('Email', _emailCtrl),
        _field('Password', _passwordCtrl, obscure: true),
      ],
    );
  }

  Widget _field(String label, TextEditingController controller, {bool obscure = false}) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: TextField(
        controller: controller,
        obscureText: obscure,
        decoration: InputDecoration(labelText: label, border: const OutlineInputBorder(), isDense: true),
      ),
    );
  }

  Widget _actionsSection() {
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        ElevatedButton(onPressed: _authenticate, child: const Text('1. Authenticate')),
        ElevatedButton(onPressed: _createAndJoin, child: const Text('2a. Create + Join + Publish (Test B/C first)')),
        SizedBox(
          width: 220,
          child: _field('Session id to join', _sessionIdCtrl),
        ),
        ElevatedButton(onPressed: _joinExisting, child: const Text('2b. Join Existing (Test A/C second)')),
        ElevatedButton(onPressed: _toggleMic, child: Text(_micEnabled ? 'Disable mic' : 'Enable mic')),
        ElevatedButton(onPressed: _leave, child: const Text('Leave session')),
      ],
    );
  }

  Widget _statusSection() {
    final sessionId = _lastSessionId;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Connection: ${_connectionState.name}', style: const TextStyle(fontWeight: FontWeight.bold)),
            if (sessionId != null) Text('Session id: $sessionId (share this with the other side)'),
            Text('Participants: ${_participants.map((p) => '${p.identity}(${p.role.name})').join(', ')}'),
          ],
        ),
      ),
    );
  }

  Widget _e2eeStatesSection() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('E2EE track states (live)', style: TextStyle(fontWeight: FontWeight.bold)),
        Expanded(
          child: _trackStates.isEmpty
              ? const Center(child: Text('No tracks yet'))
              : ListView.builder(
                  itemCount: _trackStates.length,
                  itemBuilder: (context, i) {
                    final s = _trackStates[i];
                    return ListTile(
                      dense: true,
                      leading: Icon(
                        s.state.isSecure ? Icons.lock : Icons.lock_open,
                        color: s.state.isSecure ? Colors.green : Colors.red,
                      ),
                      title: Text('${s.participantIdentity} (${s.isLocalParticipant ? "local" : "remote"}) — ${s.kind.name}'),
                      subtitle: Text('track=${s.trackSid}  state=${s.state.name}  secure=${s.state.isSecure}  at=${s.at.toIso8601String()}'),
                    );
                  },
                ),
        ),
      ],
    );
  }

  Widget _logSection() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('Event log', style: TextStyle(fontWeight: FontWeight.bold)),
        Expanded(
          child: Container(
            color: Colors.black87,
            padding: const EdgeInsets.all(6),
            child: ListView.builder(
              itemCount: _log.length,
              itemBuilder: (context, i) => Text(
                _log[i],
                style: const TextStyle(color: Colors.greenAccent, fontFamily: 'monospace', fontSize: 11),
              ),
            ),
          ),
        ),
      ],
    );
  }
}
