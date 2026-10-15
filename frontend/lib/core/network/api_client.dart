import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../config/app_config.dart';
import '../errors/app_failure.dart';
import '../storage/offline_cache.dart';
import '../storage/token_store.dart';
import '../util/json.dart';

/// Phase 0 client kept for the readiness screen (treats 503 as data).
final dioProvider = Provider<Dio>((ref) {
  return Dio(
    BaseOptions(
      baseUrl: AppConfig.apiBaseUrl,
      connectTimeout: AppConfig.connectTimeout,
      receiveTimeout: AppConfig.receiveTimeout,
      headers: {'Accept': 'application/json'},
      validateStatus: (s) => s != null && (s < 500 || s == 503),
    ),
  );
});

/// Maps the backend error envelope {"error": {"code","message","details"}} and network errors.
AppFailure mapDioError(Object error) {
  if (error is AppFailure) return error;
  if (error is DioException) {
    final data = error.response?.data;
    if (data is Map<String, dynamic> && data['error'] is Map<String, dynamic>) {
      final e = data.obj('error');
      var message = e.str('message');
      final errors = e.obj('details').objs('errors');
      if (errors.isNotEmpty) {
        message = errors
            .map((x) => '${x.str('field')}: ${x.str('message')}'.trim())
            .join('\n');
      }
      return AppFailure(e.str('code', 'error'), message);
    }
    switch (error.type) {
      case DioExceptionType.connectionError:
      case DioExceptionType.connectionTimeout:
      case DioExceptionType.receiveTimeout:
      case DioExceptionType.sendTimeout:
        return const AppFailure('network',
            'Cannot reach the Harvestique server. Check your connection.',);
      default:
        break;
    }
  }
  return AppFailure('unknown', error.toString());
}

/// A read result: live data, or the last saved copy when offline (`cachedAt` is then set).
class Loaded<T> {
  const Loaded(this.data, {this.cachedAt});

  final T data;
  final DateTime? cachedAt;

  bool get isCached => cachedAt != null;
}

/// Called when the session cannot be refreshed (the user must sign in again).
typedef AuthLost = void Function();

class ApiClient {
  ApiClient(
      {required TokenStore tokens,
      required OfflineCache cache,
      Dio? dio,
      Dio? refreshDio,})
      : _tokens = tokens,
        _cache = cache,
        _dio = dio ?? Dio(_options()),
        _refreshDio = refreshDio ?? Dio(_options()) {
    _dio.interceptors.add(
      QueuedInterceptorsWrapper(
        onRequest: (options, handler) async {
          final token = await _tokens.access();
          if (token != null && options.headers['Authorization'] == null) {
            options.headers['Authorization'] = 'Bearer $token';
          }
          handler.next(options);
        },
        onError: (err, handler) async {
          final retried = err.requestOptions.extra['retried'] == true;
          if (err.response?.statusCode == 401 &&
              !retried &&
              !err.requestOptions.path.startsWith('/auth/')) {
            final fresh = await _refresh();
            if (fresh != null) {
              final opts = err.requestOptions
                ..headers['Authorization'] = 'Bearer $fresh'
                ..extra['retried'] = true;
              try {
                // retry once on the plain client (no interceptors): avoids re-entering the queued wrapper
                handler.resolve(await _refreshDio.fetch<dynamic>(opts));
                return;
              } on DioException catch (e) {
                handler.next(e);
                return;
              }
            }
            onAuthLost?.call();
          }
          handler.next(err);
        },
      ),
    );
  }

  final TokenStore _tokens;
  final OfflineCache _cache;
  final Dio _dio;
  final Dio _refreshDio;
  AuthLost? onAuthLost;

  static BaseOptions _options() => BaseOptions(
        baseUrl: AppConfig.apiBaseUrl,
        connectTimeout: AppConfig.connectTimeout,
        receiveTimeout: AppConfig.receiveTimeout,
        headers: {'Accept': 'application/json'},
      );

  Future<String?> _refresh() async {
    final refresh = await _tokens.refresh();
    if (refresh == null) return null;
    try {
      final res = await _refreshDio
          .post<dynamic>('/auth/refresh', data: {'refresh_token': refresh});
      final body = res.data;
      if (body is! Map<String, dynamic>) return null;
      await _tokens.save(body.str('access_token'), body.str('refresh_token'));
      return body.str('access_token');
    } on DioException {
      await _tokens.clear();
      return null;
    }
  }

  Future<dynamic> _send(Future<Response<dynamic>> Function() call) async {
    try {
      return (await call()).data;
    } catch (e) {
      throw mapDioError(e);
    }
  }

  Future<Map<String, dynamic>> getObj(String path,
      {Map<String, dynamic>? query,}) async {
    final data =
        await _send(() => _dio.get<dynamic>(path, queryParameters: query));
    return data is Map<String, dynamic> ? data : <String, dynamic>{};
  }

  Future<List<Map<String, dynamic>>> getList(String path,
      {Map<String, dynamic>? query,}) async {
    return asObjects(
        await _send(() => _dio.get<dynamic>(path, queryParameters: query)),);
  }

  /// A paginated endpoint's items (first page, up to 100).
  Future<List<Map<String, dynamic>>> getPage(String path,
      {Map<String, dynamic>? query,}) async {
    final page = await getObj(path, query: {'limit': 100, ...?query});
    return page.objs('items');
  }

  /// Every item of a paged list (the server returns at most 100 per page), up to [maxItems].
  Future<List<Map<String, dynamic>>> getAll(String path, {Map<String, dynamic>? query, int maxItems = 1000}) async {
    final items = <Map<String, dynamic>>[];
    while (items.length < maxItems) {
      final page = await getObj(path, query: {...?query, 'limit': 100, 'offset': items.length});
      final batch = page.objs('items');
      items.addAll(batch);
      if (batch.isEmpty || items.length >= page.intVal('total')) break;
    }
    return items;
  }

  Future<Map<String, dynamic>> post(String path,
      {Object? body, String? idempotencyKey,}) async {
    final data = await _send(
      () => _dio.post<dynamic>(
        path,
        data: body ?? <String, dynamic>{},
        options: Options(headers: {
          if (idempotencyKey != null) 'Idempotency-Key': idempotencyKey,
        },),
      ),
    );
    return data is Map<String, dynamic> ? data : <String, dynamic>{};
  }

  /// An assistant question. The server may consult a local AI model, which can take tens of seconds on a CPU-only
  /// machine, so this waits up to [AppConfig.assistantTimeout] instead of the normal receive timeout.
  Future<Map<String, dynamic>> ask(
      String path, Map<String, dynamic> body,) async {
    final data = await _send(
      () => _dio.post<dynamic>(path,
          data: body,
          options: Options(receiveTimeout: AppConfig.assistantTimeout),),
    );
    return data is Map<String, dynamic> ? data : <String, dynamic>{};
  }

  Future<Map<String, dynamic>> patch(
      String path, Map<String, dynamic> body,) async {
    final data = await _send(() => _dio.patch<dynamic>(path, data: body));
    return data is Map<String, dynamic> ? data : <String, dynamic>{};
  }

  Future<void> delete(String path) async {
    await _send(() => _dio.delete<dynamic>(path));
  }

  Future<Map<String, dynamic>> upload(
    String path, {
    required String field,
    required List<int> bytes,
    required String filename,
    Map<String, String> fields = const {},
    Duration? receiveTimeout,
  }) async {
    final form = FormData.fromMap(
        {...fields, field: MultipartFile.fromBytes(bytes, filename: filename)},);
    final data = await _send(
      () => _dio.post<dynamic>(path,
          data: form,
          options: Options(
              receiveTimeout: receiveTimeout ?? AppConfig.receiveTimeout,),),
    );
    return data is Map<String, dynamic> ? data : <String, dynamic>{};
  }

  /// Read with the offline fallback: on success the response is saved; when the server is unreachable the
  /// last saved copy is returned with its timestamp. Other errors are never hidden.
  Future<Loaded<T>> cached<T>(String key, Future<T> Function() fetch,
      T Function(Object? json) decode,) async {
    try {
      final live = await fetch();
      await _cache.put(key, live);
      return Loaded(live);
    } on AppFailure catch (f) {
      if (!f.isOffline) rethrow;
      final saved = await _cache.get(key);
      if (saved == null) rethrow;
      return Loaded(decode(saved.data), cachedAt: saved.savedAt);
    }
  }
}

final apiProvider = Provider<ApiClient>((ref) {
  return ApiClient(
      tokens: ref.watch(tokenStoreProvider),
      cache: ref.watch(offlineCacheProvider),);
});
