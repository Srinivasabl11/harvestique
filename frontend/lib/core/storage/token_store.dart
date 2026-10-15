import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Access and refresh tokens, kept in Android Keystore-backed secure storage (never in plain preferences).
class TokenStore {
  TokenStore([FlutterSecureStorage? storage]) : _storage = storage ?? const FlutterSecureStorage();

  final FlutterSecureStorage _storage;
  static const _access = 'access_token';
  static const _refresh = 'refresh_token';
  String? _cachedAccess;

  Future<String?> access() async => _cachedAccess ??= await _storage.read(key: _access);

  Future<String?> refresh() => _storage.read(key: _refresh);

  Future<void> save(String access, String refresh) async {
    _cachedAccess = access;
    await _storage.write(key: _access, value: access);
    await _storage.write(key: _refresh, value: refresh);
  }

  Future<void> clear() async {
    _cachedAccess = null;
    await _storage.delete(key: _access);
    await _storage.delete(key: _refresh);
  }
}

final tokenStoreProvider = Provider<TokenStore>((ref) => TokenStore());
