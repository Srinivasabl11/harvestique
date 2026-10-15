import 'package:flutter_test/flutter_test.dart';
import 'package:harvestique/core/errors/app_failure.dart';
import 'package:harvestique/core/network/api_client.dart';
import 'package:harvestique/core/storage/offline_cache.dart';
import 'package:harvestique/core/storage/token_store.dart';

class MemoryCache extends OfflineCache {
  final store = <String, CachedEntry>{};

  @override
  Future<void> put(String key, Object? json) async => store[key] = CachedEntry(json, DateTime(2026, 10, 8, 9));

  @override
  Future<CachedEntry?> get(String key) async => store[key];
}

class NoTokens extends TokenStore {
  @override
  Future<String?> access() async => null;

  @override
  Future<String?> refresh() async => null;
}

void main() {
  late MemoryCache cache;
  late ApiClient api;

  setUp(() {
    cache = MemoryCache();
    api = ApiClient(tokens: NoTokens(), cache: cache);
  });

  List<String> decode(Object? j) => (j as List<dynamic>).cast<String>();

  test('live data is returned and saved', () async {
    final r = await api.cached('k', () async => ['a'], decode);
    expect(r.data, ['a']);
    expect(r.isCached, isFalse);
    expect(cache.store['k']!.data, ['a']);
  });

  test('offline falls back to the saved copy and says when it was saved', () async {
    await api.cached('k', () async => ['saved'], decode);
    final r = await api.cached<List<String>>('k', () async => throw const AppFailure('network', 'down'), decode);
    expect(r.data, ['saved']);
    expect(r.isCached, isTrue);
    expect(r.cachedAt, DateTime(2026, 10, 8, 9));
  });

  test('offline with nothing saved is an error, not empty data', () async {
    expect(
      () => api.cached<List<String>>('none', () async => throw const AppFailure('network', 'down'), decode),
      throwsA(isA<AppFailure>()),
    );
  });

  test('server errors are never hidden behind the cache', () async {
    await api.cached('k', () async => ['saved'], decode);
    expect(
      () => api.cached<List<String>>('k', () async => throw const AppFailure('permission_denied', 'no'), decode),
      throwsA(isA<AppFailure>().having((f) => f.code, 'code', 'permission_denied')),
    );
  });
}
