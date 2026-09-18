/// Base type for every exception this SDK throws. Consuming apps can
/// catch [AyurezeException] to handle any SDK failure uniformly, or a
/// specific subtype for finer-grained handling.
sealed class AyurezeException implements Exception {
  final String message;
  const AyurezeException(this.message);

  @override
  String toString() => '$runtimeType: $message';
}

/// The SDK method was called before [AyurezeTelehealthClient.initialize]
/// or before [AyurezeTelehealthClient.authenticate].
class NotInitializedException extends AyurezeException {
  const NotInitializedException(super.message);
}

/// The Go API rejected a request — e.g. bad credentials, not authorized
/// for this session, session ended. [statusCode] and [errorCode] mirror
/// the Go API's `{"error": "<code>", "message": "..."}` response shape
/// (see docs/api/README.md).
class ApiException extends AyurezeException {
  final int statusCode;
  final String errorCode;
  const ApiException(this.statusCode, this.errorCode, super.message);
}

/// Failed to connect to, or was disconnected from, the LiveKit room.
class ConnectionException extends AyurezeException {
  const ConnectionException(super.message);
}
