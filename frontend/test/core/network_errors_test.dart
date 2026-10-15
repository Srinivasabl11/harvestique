import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:harvestique/core/network/api_client.dart';

/// "Cannot reach the server" must say WHY, so a connection problem can be traced to its cause (and a wrong build
/// address is visible), and every such failure must still count as offline (screens then show saved data).
void main() {
  AppFailureMatcher f(DioExceptionType type, {Object? cause, int? status}) =>
      AppFailureMatcher(networkFailure(type, cause, status, host: 'harvestique-api.onrender.com'));

  test('no internet or DNS', () {
    final r = f(DioExceptionType.connectionError, cause: "SocketException: Failed host lookup: 'harvestique-api.onrender.com'");
    expect(r.message, contains('No internet connection'));
    expect(r.message, contains('harvestique-api.onrender.com'));
    expect(r.offline, isTrue);
  });

  test('TLS problems point at the phone clock', () {
    expect(f(DioExceptionType.connectionError, cause: 'HandshakeException: CERTIFICATE_VERIFY_FAILED').message, contains('date and time'));
    expect(f(DioExceptionType.badCertificate).message, contains('date and time'));
  });

  test('refused, waking up, slow', () {
    expect(f(DioExceptionType.connectionError, cause: 'SocketException: Connection refused').message, contains('refused'));
    expect(f(DioExceptionType.connectionTimeout).message, contains('starting up'));
    expect(f(DioExceptionType.receiveTimeout).message, contains('waking up'));
  });

  test('a hosting proxy 502/503/504 means starting or deploying, and still counts as offline', () {
    for (final s in [502, 503, 504]) {
      final r = f(DioExceptionType.badResponse, status: s);
      expect(r.code, 'server_unavailable');
      expect(r.offline, isTrue);
    }
    expect(networkFailure(DioExceptionType.badResponse, null, 500), isNull); // a real server error keeps its body
  });

  test('the server host is shown, not the whole URL', () {
    expect(serverHost('https://harvestique-api.onrender.com/api/v1'), 'harvestique-api.onrender.com');
    expect(serverHost('http://10.0.2.2:8000/api/v1'), '10.0.2.2');
  });

  test('an error envelope from the server is used as is (with its reference)', () {
    final e = DioException(
      requestOptions: RequestOptions(path: '/x'),
      type: DioExceptionType.badResponse,
      response: Response(
        requestOptions: RequestOptions(path: '/x'),
        statusCode: 500,
        data: {'error': {'code': 'internal_error', 'message': 'Internal server error (reference abc123)', 'details': {}}},
      ),
    );
    final r = mapDioError(e);
    expect(r.code, 'internal_error');
    expect(r.message, contains('reference abc123'));
  });
}

class AppFailureMatcher {
  AppFailureMatcher(this._f) : assert(_f != null);
  final dynamic _f;
  String get message => _f.message as String;
  String get code => _f.code as String;
  bool get offline => _f.isOffline as bool;
}
