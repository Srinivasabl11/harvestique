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

  /// Step 1 of 2: phone + password. Never signs in by itself: returns the one-time-code challenge
  /// (the server sends the code by SMS; see [verify]).
  Future<Map<String, dynamic>> login(String phone, String password) =>
      _api.post('/auth/login', body: {'phone': phone, 'password': password});

  /// Step 1 of 2: create the (pending) account and get the code challenge.
  Future<Map<String, dynamic>> register(Map<String, dynamic> body) => _api.post('/auth/register', body: body);

  /// Step 2 of 2: the code from the SMS. Only now are tokens issued and the user signed in.
  Future<void> verify(String purpose, String challengeId, String code) async {
    final res = await _api.post('/auth/$purpose/verify', body: {'challenge_id': challengeId, 'code': code});
    await _accept(res);
  }

  /// Forgot password, step 1: a code is sent if the number has an account (the answer is the same either way).
  Future<Map<String, dynamic>> forgotPassword(String phone) => _api.post('/auth/password/forgot', body: {'phone': phone});

  /// Forgot password, step 2: the code and the new password. Signs out every session; then sign in normally.
  Future<void> resetPassword(String challengeId, String code, String newPassword) async {
    await _api.post('/auth/password/reset', body: {'challenge_id': challengeId, 'code': code, 'new_password': newPassword});
  }

  /// Records that this version of the guided tour was finished or skipped (stored per account on the server).
  Future<void> markTourSeen(int version) async {
    final user = await _api.post('/auth/me/tour', body: {'version': version});
    state = AuthState(AuthStatus.signedIn, user: user);
  }

  /// A new code for the same challenge (cooldown and limits apply on the server).
  Future<Map<String, dynamic>> resend(String challengeId) => _api.post('/auth/otp/resend', body: {'challenge_id': challengeId});

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
