import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:harvestique/core/network/api_client.dart';
import 'package:harvestique/core/storage/offline_cache.dart';
import 'package:harvestique/core/storage/token_store.dart';
import 'package:harvestique/features/admin/admin_screens.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _NoTokens extends TokenStore {
  @override
  Future<String?> access() async => null;

  @override
  Future<String?> refresh() async => null;
}

class _FakeApi extends ApiClient {
  _FakeApi() : super(tokens: _NoTokens(), cache: OfflineCache());

  final queries = <String?>[];
  final posts = <(String, Object?)>[];

  @override
  Future<List<Map<String, dynamic>>> getPage(String path, {Map<String, dynamic>? query}) async {
    queries.add(query?['access'] as String?);
    if (query?['access'] != 'pending') return [];
    return [
      {
        'id': 'u1',
        'full_name': 'Ravi Kumar',
        'role': 'farmer',
        'phone': '+919800000001',
        'access_status': 'pending',
        'created_at': '2026-10-15T08:00:00Z',
      },
    ];
  }

  @override
  Future<Map<String, dynamic>> post(String path, {Object? body, String? idempotencyKey}) async {
    posts.add((path, body));
    return {'id': 'u1', 'access_status': 'approved'};
  }
}

void main() {
  testWidgets('admin sees waiting sign-ups and approves one', (tester) async {
    SharedPreferences.setMockInitialValues({});
    final api = _FakeApi();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [apiProvider.overrideWithValue(api), tokenStoreProvider.overrideWithValue(_NoTokens())],
        child: const MaterialApp(home: Scaffold(body: TestersScreen())),
      ),
    );
    await tester.pumpAndSettle();
    expect(api.queries, ['pending']);
    expect(find.text('Ravi Kumar'), findsOneWidget);

    await tester.tap(find.byTooltip('Change access'));
    await tester.pumpAndSettle();
    expect(find.text('Approve'), findsOneWidget);
    expect(find.text('Revoke access'), findsOneWidget);
    await tester.tap(find.text('Approve'));
    await tester.pumpAndSettle();
    expect(api.posts.single.$1, '/admin/users/u1/access');
    expect(api.posts.single.$2, {'status': 'approved'});
  });

  testWidgets('revoking asks for confirmation first', (tester) async {
    SharedPreferences.setMockInitialValues({});
    final api = _FakeApi();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [apiProvider.overrideWithValue(api), tokenStoreProvider.overrideWithValue(_NoTokens())],
        child: const MaterialApp(home: Scaffold(body: TestersScreen())),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Change access'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Revoke access'));
    await tester.pumpAndSettle();
    expect(find.text('Revoke access?'), findsOneWidget);
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();
    expect(api.posts, isEmpty);

    await tester.tap(find.text('Suspended'));
    await tester.pumpAndSettle();
    expect(api.queries.last, 'suspended');
    expect(find.text('No accounts here.'), findsOneWidget);
  });
}
