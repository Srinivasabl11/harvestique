import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/network/api_client.dart';
import '../../core/storage/offline_cache.dart';
import '../../core/storage/token_store.dart';
import '../../core/util/json.dart';

enum AuthStatus { unknown, signedOut, signedIn }

@immutable
class AuthState {
  const AuthState(this.status, {this.user = const <String, dynamic>{}});

  final AuthStatus status;
  final Map<String, dynamic> user;

  String get role => user.str('role');
  String get name => user.str('full_name');
  String get phone => user.str('phone');

  /// Preferred language from the farmer profile ("en" or "kn"); used for assistant replies and voice.
  String get language => user.obj('farmer_profile').str('preferred_language', 'en');
}

class AuthController extends StateNotifier<AuthState> {
  AuthController(this._api, this._tokens, this._cache) : super(const AuthState(AuthStatus.unknown)) {
    _api.onAuthLost = () => state = const AuthState(AuthStatus.signedOut);
    restore();
  }

  final ApiClient _api;
  final TokenStore _tokens;
  final OfflineCache _cache;

  Future<void> restore() async {
    if (await _tokens.access() == null) {
      state = const AuthState(AuthStatus.signedOut);
      return;
    }
    try {
      state = AuthState(AuthStatus.signedIn, user: await _api.getObj('/auth/me'));
    } catch (_) {
      state = const AuthState(AuthStatus.signedOut);
    }
  }

  /// Phone + password. Signs in directly (no SMS code). Throws an AppFailure with code
  /// `password_change_required` after an admin password reset: then call [changePassword].
  Future<void> login(String phone, String password) async {
    await _accept(await _api.post('/auth/login', body: {'phone': phone, 'password': password}));
  }

  /// Creates the account. Returns null when it is usable at once (signed in), or the server's message when it
  /// waits for an admin's approval (no tokens are issued until then).
  Future<String?> register(Map<String, dynamic> body) async {
    final res = await _api.post('/auth/register', body: body);
    if (res['tokens'] is Map<String, dynamic>) {
      await _accept(res);
      return null;
    }
    return res.str('message', 'Your account is waiting for approval.');
  }

  /// Sets a new password with the current (or admin-issued temporary) one. Signs out every other device and
  /// signs in here with a fresh session.
  Future<void> changePassword(String phone, String currentPassword, String newPassword) async {
    await _accept(await _api.post(
      '/auth/password/change',
      body: {'phone': phone, 'current_password': currentPassword, 'new_password': newPassword},
    ),);
  }

  /// Records that this version of the guided tour was finished or skipped (stored per account on the server).
  Future<void> markTourSeen(int version) async {
    final user = await _api.post('/auth/me/tour', body: {'version': version});
    state = AuthState(AuthStatus.signedIn, user: user);
  }

  Future<void> _accept(Map<String, dynamic> res) async {
    final tokens = res.obj('tokens');
    await _tokens.save(tokens.str('access_token'), tokens.str('refresh_token'));
    state = AuthState(AuthStatus.signedIn, user: res.obj('user'));
  }

  Future<void> refreshUser() async {
    state = AuthState(AuthStatus.signedIn, user: await _api.getObj('/auth/me'));
  }

  Future<void> logout() async {
    try {
      await _api.post('/auth/logout');
    } catch (_) {
      // signing out locally is what matters
    }
    await _tokens.clear();
    await _cache.clear();
    state = const AuthState(AuthStatus.signedOut);
  }
}

final authProvider = StateNotifierProvider<AuthController, AuthState>((ref) {
  return AuthController(ref.watch(apiProvider), ref.watch(tokenStoreProvider), ref.watch(offlineCacheProvider));
});
