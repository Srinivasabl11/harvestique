import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:harvestique/core/errors/app_failure.dart';
import 'package:harvestique/core/network/api_client.dart';
import 'package:harvestique/core/storage/offline_cache.dart';
import 'package:harvestique/core/storage/token_store.dart';
import 'package:harvestique/features/auth/auth_controller.dart';
import 'package:harvestique/features/auth/change_password_screen.dart';
import 'package:harvestique/features/auth/login_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Token store double that records what was saved.
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

const _signedIn = {
  'user': {'id': 'u1', 'role': 'farmer', 'full_name': 'Ramesh', 'phone': '+919876543210'},
  'tokens': {'access_token': 'access-1', 'refresh_token': 'refresh-1'},
};

class _FakeApi extends ApiClient {
  _FakeApi(TokenStore tokens) : super(tokens: tokens, cache: OfflineCache());

  final posts = <(String, Object?)>[];
  Map<String, dynamic> registerAnswer = {
    'status': 'pending',
    'message': 'Thank you. Your account is waiting for approval by the Harvestique team.',
    'user': null,
    'tokens': null,
  };
  bool mustChange = false;

  @override
  Future<Map<String, dynamic>> post(String path, {Object? body, String? idempotencyKey}) async {
    posts.add((path, body));
    switch (path) {
      case '/auth/login':
        if (mustChange) throw const AppFailure('password_change_required', 'Please set a new password to continue.');
        return _signedIn;
      case '/auth/register':
        return registerAnswer;
      case '/auth/password/change':
        final current = (body! as Map<String, dynamic>)['current_password'];
        if (current != 'k7mp-2qxa-9rtd') throw const AppFailure('invalid_credentials', 'Invalid phone number or password');
        return _signedIn;
    }
    throw StateError('unexpected POST $path');
  }
}

Future<(_FakeApi, _Tokens, ProviderContainer)> _setUp() async {
  SharedPreferences.setMockInitialValues({});
  final tokens = _Tokens();
  final api = _FakeApi(tokens);
  final container = ProviderContainer(overrides: [
    tokenStoreProvider.overrideWithValue(tokens),
    apiProvider.overrideWithValue(api),
  ],);
  addTearDown(container.dispose);
  await container.read(authProvider.notifier).restore();
  return (api, tokens, container);
}

void main() {
  test('sign-in with phone and password signs in directly (no code step)', () async {
    final (api, tokens, container) = await _setUp();
    await container.read(authProvider.notifier).login('+919876543210', 'Harvest123');
    expect(api.posts.single.$1, '/auth/login');
    expect(api.posts.single.$2, {'phone': '+919876543210', 'password': 'Harvest123'});
    expect(tokens.saved, 'access-1');
    expect(container.read(authProvider).status, AuthStatus.signedIn);
  });

  test('a sign-up waiting for approval stores no tokens and returns the server message', () async {
    final (api, tokens, container) = await _setUp();
    final message = await container.read(authProvider.notifier).register({'role': 'farmer'});
    expect(message, contains('waiting for approval'));
    expect(tokens.saved, isNull);
    expect(container.read(authProvider).status, AuthStatus.signedOut);

    api.registerAnswer = {'status': 'approved', 'message': 'Account created.', ..._signedIn};
    expect(await container.read(authProvider.notifier).register({'role': 'farmer'}), isNull);
    expect(container.read(authProvider).status, AuthStatus.signedIn);
  });

  test('a temporary password is refused for sign-in until it is changed', () async {
    final (api, tokens, container) = await _setUp();
    api.mustChange = true;
    await expectLater(
      container.read(authProvider.notifier).login('+919876543210', 'k7mp-2qxa-9rtd'),
      throwsA(isA<AppFailure>().having((f) => f.code, 'code', 'password_change_required')),
    );
    expect(tokens.saved, isNull);
  });

  testWidgets('the forced change takes the temporary password and a new one, then signs in', (tester) async {
    final (api, tokens, container) = await _setUp();
    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: const MaterialApp(home: ChangePasswordScreen(phone: '+919876543210', forced: true)),
      ),
    );
    expect(find.textContaining('temporary password'), findsWidgets);
    final fields = find.byType(TextFormField);
    await tester.enterText(fields.at(0), 'k7mp-2qxa-9rtd');
    await tester.enterText(fields.at(1), 'NewHarvest456');
    await tester.enterText(fields.at(2), 'Different789');
    await tester.tap(find.text('Save new password'));
    await tester.pump();
    expect(find.text('The passwords do not match'), findsOneWidget);
    expect(api.posts, isEmpty);

    await tester.enterText(fields.at(2), 'NewHarvest456');
    await tester.tap(find.text('Save new password'));
    await tester.pump();
    await tester.pump();
    expect(api.posts.single.$1, '/auth/password/change');
    expect(api.posts.single.$2, {
      'phone': '+919876543210',
      'current_password': 'k7mp-2qxa-9rtd',
      'new_password': 'NewHarvest456',
    });
    expect(tokens.saved, 'access-1');
    expect(container.read(authProvider).status, AuthStatus.signedIn);
  });

  testWidgets('a wrong temporary password shows the error and signs nobody in', (tester) async {
    final (_, tokens, container) = await _setUp();
    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: const MaterialApp(home: ChangePasswordScreen(phone: '+919876543210', forced: true)),
      ),
    );
    final fields = find.byType(TextFormField);
    await tester.enterText(fields.at(0), 'wrong-pass-1');
    await tester.enterText(fields.at(1), 'NewHarvest456');
    await tester.enterText(fields.at(2), 'NewHarvest456');
    await tester.tap(find.text('Save new password'));
    await tester.pump();
    await tester.pump();
    expect(find.text('Invalid phone number or password'), findsOneWidget);
    expect(tokens.saved, isNull);
  });

  testWidgets('forgot password explains the admin reset instead of sending a code', (tester) async {
    final (_, _, container) = await _setUp();
    await tester.pumpWidget(
      UncontrolledProviderScope(container: container, child: const MaterialApp(home: LoginScreen())),
    );
    await tester.tap(find.text('Forgot password?'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Ask the Harvestique team to reset it'), findsOneWidget);
    expect(find.textContaining('temporary password'), findsOneWidget);
  });
}
