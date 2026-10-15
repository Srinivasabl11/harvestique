import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:harvestique/core/errors/app_failure.dart';
import 'package:harvestique/core/network/api_client.dart';
import 'package:harvestique/core/storage/offline_cache.dart';
import 'package:harvestique/core/storage/token_store.dart';
import 'package:harvestique/features/auth/auth_controller.dart';
import 'package:harvestique/features/auth/otp_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Token store double that records what was saved (tokens must only be saved after a verified code).
class _Tokens extends TokenStore {
  String? saved;

  @override
  Future<String?> access() async => saved;

  @override
  Future<String?> refresh() async => null;

  @override
  Future<void> save(String access, String refresh) async => saved = access;

  @override
  Future<void> clear() async => saved = null;
}

class _FakeApi extends ApiClient {
  _FakeApi(TokenStore tokens) : super(tokens: tokens, cache: OfflineCache());

  final posts = <(String, Object?)>[];
  String correct = '482913';

  @override
  Future<Map<String, dynamic>> post(String path, {Object? body, String? idempotencyKey}) async {
    posts.add((path, body));
    if (path == '/auth/login/verify') {
      final code = (body! as Map<String, dynamic>)['code'];
      if (code != correct) throw const AppFailure('invalid_otp', 'The code is not correct. 4 attempts left.');
      return {
        'user': {'id': 'u1', 'role': 'farmer', 'full_name': 'Ramesh'},
        'tokens': {'access_token': 'access-1', 'refresh_token': 'refresh-1'},
      };
    }
    if (path == '/auth/otp/resend') return {..._challenge(), 'resend_after': 60, 'message': 'resent'};
    throw StateError('unexpected POST $path');
  }
}

Map<String, dynamic> _challenge({bool dev = false, int resendAfter = 0}) => {
      'challenge_id': 'c1',
      'purpose': 'login',
      'phone_hint': '+91******3210',
      'code_length': 6,
      'expires_in': 300,
      'resend_after': resendAfter,
      'attempts_left': 5,
      'delivery': dev ? 'development_console' : 'sms',
      'dev_code': dev ? '482913' : null,
      'message': dev ? 'DEVELOPMENT MODE: no SMS was sent.' : 'A 6-digit code was sent by SMS to +91******3210.',
    };

Future<(_FakeApi, _Tokens, ProviderContainer)> _pump(WidgetTester tester, Map<String, dynamic> challenge) async {
  SharedPreferences.setMockInitialValues({});
  final tokens = _Tokens();
  final api = _FakeApi(tokens);
  final container = ProviderContainer(overrides: [
    tokenStoreProvider.overrideWithValue(tokens),
    apiProvider.overrideWithValue(api),
  ],);
  addTearDown(container.dispose);
  await tester.pumpWidget(
    UncontrolledProviderScope(container: container, child: MaterialApp(home: OtpScreen(challenge: challenge))),
  );
  await tester.pump();
  return (api, tokens, container);
}

void main() {
  testWidgets('a real SMS challenge shows no code, and a wrong code signs nobody in', (tester) async {
    final (api, tokens, container) = await _pump(tester, _challenge());
    expect(find.textContaining('sent by SMS to +91******3210'), findsOneWidget);
    expect(find.textContaining('DEVELOPMENT MODE'), findsNothing);

    await tester.enterText(find.byType(TextField), '111111'); // full length: submits by itself
    await tester.pump();
    await tester.pump();
    expect(find.text('The code is not correct. 4 attempts left.'), findsOneWidget);
    expect(tokens.saved, isNull);
    expect(container.read(authProvider).status, isNot(AuthStatus.signedIn));
  });

  testWidgets('the right code signs in and only then stores the tokens', (tester) async {
    final (api, tokens, container) = await _pump(tester, _challenge());
    await tester.enterText(find.byType(TextField), '482913');
    await tester.pump();
    await tester.pump();
    expect(api.posts.last.$1, '/auth/login/verify');
    expect(api.posts.last.$2, {'challenge_id': 'c1', 'code': '482913'});
    expect(tokens.saved, 'access-1');
    expect(container.read(authProvider).status, AuthStatus.signedIn);
  });

  testWidgets('development mode is clearly labelled as not sent by SMS', (tester) async {
    await _pump(tester, _challenge(dev: true));
    expect(find.text('DEVELOPMENT MODE – not sent by SMS'), findsOneWidget);
    expect(find.textContaining('returned the code: 482913'), findsOneWidget);
  });

  testWidgets('resend waits for the cooldown and short codes are not sent', (tester) async {
    final (api, _, _) = await _pump(tester, _challenge(resendAfter: 2));
    expect(find.text('Send a new code in 2 s'), findsOneWidget);
    expect(tester.widget<TextButton>(find.widgetWithText(TextButton, 'Send a new code in 2 s')).onPressed, isNull);
    await tester.pump(const Duration(seconds: 2));
    expect(find.text('Send a new code'), findsOneWidget);
    await tester.tap(find.text('Send a new code'));
    await tester.pump();
    await tester.pump();
    expect(api.posts.last.$1, '/auth/otp/resend');
    expect(find.textContaining('previous code no longer works'), findsOneWidget);

    await tester.enterText(find.byType(TextField), '123');
    await tester.tap(find.text('Verify and sign in'));
    await tester.pump();
    expect(find.text('Enter the 6-digit code.'), findsOneWidget);
    expect(api.posts.where((p) => p.$1.endsWith('/verify')), isEmpty);
  });
}
