/// UI-facing failure type. Repositories convert transport errors into this,
/// so widgets never handle Dio exceptions directly.
class AppFailure implements Exception {
  const AppFailure(this.code, this.message);

  final String code;
  final String message;

  /// True when the server could not be reached (no network, timeout, or the host's proxy says it is starting).
  bool get isOffline => code == 'network' || code == 'server_unavailable';

  @override
  String toString() => 'AppFailure($code): $message';
}
