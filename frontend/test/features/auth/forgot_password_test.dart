import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:harvestique/core/errors/app_failure.dart';
import 'package:harvestique/core/network/api_client.dart';
import 'package:harvestique/core/storage/offline_cache.dart';
import 'package:harvestique/core/storage/token_store.dart';
import 'package:harvestique/features/auth/forgot_password_screen.dart';
import 'package:harvestique/features/auth/login_screen.dart';

class _NoTokens extends TokenStore {
  @override
  Future<String?> access() async => null;

  @override
  Future<String?> refresh() async => null;
}

class _FakeApi extends ApiClient {
  _FakeApi({this.dev = true}) : super(tokens: _NoTokens(), cache: OfflineCache());

  final bool dev;
  final posts = <(String, Object?)>[];
  AppFailure? resetFails;

  @override
  Future<Map<String, dynamic>> post(String path, {Object? body, String? idempotencyKey}) async {
    posts.add((path, body));
    if (path == '/auth/password/forgot') {
      return {
        'challenge_id': 'c1',
        'purpose': 'password_reset',
        'phone_hint': '+91******3210',
        'code_length': 6,
        'expires_in': 300,
        'resend_after': 60,
        'attempts_left': 5,
        'delivery': dev ? 'development_console' : 'sms',
        'dev_code': dev ? '123456' : null,
        'message': dev ? 'DEVELOPMENT MODE: no SMS was sent.' : 'If an account uses this number, a 6-digit code was sent by SMS to +91******3210.',
      };
    }
    if (path == '/auth/password/reset') {
      if (resetFails != null) throw resetFails!;
      return {};
    }
    throw StateError(path);
  }
}

Widget _app(ApiClient api, {String start = ForgotPasswordScreen.routePath}) {
  final router = GoRouter(
    initialLocation: start,
    routes: [
      GoRoute(path: LoginScreen.routePath, builder: (_, __) => const LoginScreen()),
      GoRoute(path: ForgotPasswordScreen.routePath, builder: (_, __) => const ForgotPasswordScreen()),
      GoRoute(path: '/register', builder: (_, __) => const Scaffold()),
    ],
  );
  return ProviderScope(
    overrides: [apiProvider.overrideWithValue(api), tokenStoreProvider.overrideWithValue(_NoTokens())],
    child: MaterialApp.router(routerConfig: router),
  );
}

Future<void> _requestCode(WidgetTester tester) async {
  await tester.enterText(find.widgetWithText(TextFormField, 'Mobile number'), '9876543210');
  await tester.tap(find.text('Send code'));
  await tester.pumpAndSettle();
}

Future<void> _fill(WidgetTester tester, String code, String pw, String confirm) async {
  await tester.enterText(find.widgetWithText(TextFormField, '6-digit code'), code);
  await tester.enterText(find.widgetWithText(TextFormField, 'New password (8+ letters and numbers)'), pw);
  await tester.enterText(find.widgetWithText(TextFormField, 'Confirm new password'), confirm);
  await tester.ensureVisible(find.text('Set new password'));
  await tester.tap(find.text('Set new password'));
  await tester.pumpAndSettle();
}

void main() {
  test('password rule matches the server', () {
    expect(validateNewPassword('Harvest123'), isNull);
    expect(validateNewPassword('short1'), contains('8'));
    expect(validateNewPassword('lettersonly'), contains('letters and numbers'));
    expect(validateNewPassword('12345678'), contains('letters and numbers'));
  });

  testWidgets('the login screen offers "Forgot password?"', (tester) async {
    await tester.pumpWidget(_app(_FakeApi(), start: LoginScreen.routePath));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Forgot password?'));
    await tester.pumpAndSettle();
    expect(find.text('Reset password'), findsOneWidget);
  });

  testWidgets('number -> labelled development code -> new password -> back to sign in', (tester) async {
    final api = _FakeApi();
    await tester.pumpWidget(_app(api));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Send code'));
    await tester.pumpAndSettle();
    expect(find.text('Enter your mobile number'), findsOneWidget);
    expect(api.posts, isEmpty);

    await _requestCode(tester);
    expect(api.posts.single.$2, {'phone': '+919876543210'});
    expect(find.text('DEVELOPMENT MODE – not sent by SMS'), findsOneWidget);
    expect(find.text('Send a new code in 60 s'), findsOneWidget);

    await _fill(tester, '123456', 'NewHarvest456', 'Different789');
    expect(find.text('The passwords do not match'), findsOneWidget);
    await _fill(tester, '123456', 'weak', 'weak');
    expect(find.text('At least 8 characters'), findsOneWidget);
    expect(api.posts, hasLength(1));

    await _fill(tester, '123456', 'NewHarvest456', 'NewHarvest456');
    expect(api.posts.last.$1, '/auth/password/reset');
    expect(api.posts.last.$2, {'challenge_id': 'c1', 'code': '123456', 'new_password': 'NewHarvest456'});
    expect(find.text('Sign in'), findsOneWidget); // back on the login screen
    expect(find.text('Password changed. Sign in with your new password.'), findsOneWidget);
  });

  testWidgets('a real SMS setup shows no code, and a server rejection stays on screen', (tester) async {
    final api = _FakeApi(dev: false)..resetFails = const AppFailure('invalid_otp', 'The code is not correct. 4 attempts left.');
    await tester.pumpWidget(_app(api));
    await tester.pumpAndSettle();
    await _requestCode(tester);
    expect(find.textContaining('If an account uses this number'), findsOneWidget);
    expect(find.textContaining('DEVELOPMENT MODE'), findsNothing);
    await _fill(tester, '000000', 'NewHarvest456', 'NewHarvest456');
    expect(find.text('The code is not correct. 4 attempts left.'), findsOneWidget);
    expect(find.text('Set new password'), findsOneWidget);
  });
}
