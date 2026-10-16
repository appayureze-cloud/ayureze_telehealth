import 'dart:async';

import 'models/models.dart';

/// Tracks the latest [AyurezeE2EEState] for every track currently known to
/// the session and broadcasts changes as they happen.
///
/// Deliberately free of any `livekit_client` types: [AyurezeTelehealthClient]
/// is the only place that touches real LiveKit event objects, and it
/// extracts just the few safe fields (`participant.identity`,
/// `publication.sid`, `publication.kind`, the `E2EEState`) before handing
/// them to this class. That split keeps the actual state-management and
/// fail-closed logic — the part worth testing — runnable in a plain unit
/// test with no LiveKit room, connection, or Android runtime required.
///
/// Never holds or exposes key material, ciphertext, plaintext, or raw
/// media — see [AyurezeE2EETrackState]'s own doc comment.
class AyurezeE2EEDiagnostics {
  final Map<String, AyurezeE2EETrackState> _states = {};
  final StreamController<AyurezeE2EETrackState> _controller = StreamController<AyurezeE2EETrackState>.broadcast();

  /// Fires every time a track's E2EE state changes (including the first
  /// time it's observed). Does not fire for track/participant removal —
  /// use [all] or re-derive from your own bookkeeping if you need to
  /// notice a track disappearing, since a track that's gone is different
  /// from a track that's known and insecure.
  Stream<AyurezeE2EETrackState> get stateChanges => _controller.stream;

  /// A snapshot of every currently-known track's latest state, in no
  /// particular order.
  List<AyurezeE2EETrackState> get all => _states.values.toList(growable: false);

  /// Records a new state for [trackSid], keyed by that stable id (never
  /// by display name — see [AyurezeE2EETrackState]). Overwrites any
  /// previous state for the same track. Always broadcasts, even if the
  /// new state equals the old one, since each event reflects a real
  /// signal LiveKit just sent, not a derived/debounced value.
  void recordState({
    required String participantIdentity,
    required bool isLocalParticipant,
    required String trackSid,
    required AyurezeTrackKind kind,
    required AyurezeE2EEState state,
    DateTime? at,
  }) {
    final snapshot = AyurezeE2EETrackState(
      participantIdentity: participantIdentity,
      isLocalParticipant: isLocalParticipant,
      trackSid: trackSid,
      kind: kind,
      state: state,
      at: at ?? DateTime.now(),
    );
    _states[trackSid] = snapshot;
    if (!_controller.isClosed) {
      _controller.add(snapshot);
    }
  }

  /// Removes state for a single track (unpublished/unsubscribed). Safe to
  /// call for a track that was never recorded.
  void removeTrack(String trackSid) {
    _states.remove(trackSid);
  }

  /// Removes state for every track belonging to [participantIdentity]
  /// (participant disconnected). Safe to call for an identity with no
  /// recorded tracks.
  void removeParticipant(String participantIdentity) {
    _states.removeWhere((_, s) => s.participantIdentity == participantIdentity);
  }

  /// Clears all recorded state (room disconnected, or about to join a
  /// new one — stale state from a previous session must never leak into
  /// a new one's diagnostics).
  void clear() {
    _states.clear();
  }

  /// Releases the underlying stream controller. Call once, when the
  /// owning client is disposed.
  Future<void> dispose() async {
    _states.clear();
    await _controller.close();
  }
}
