import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:harvestique/core/network/api_client.dart';
import 'package:harvestique/core/storage/offline_cache.dart';
import 'package:harvestique/core/storage/token_store.dart';
import 'package:harvestique/features/buyer/demands_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _NoTokens extends TokenStore {
  @override
  Future<String?> access() async => null;

  @override
  Future<String?> refresh() async => null;
}

class _FakeApi extends ApiClient {
  _FakeApi() : super(tokens: _NoTokens(), cache: OfflineCache());

  final posts = <String>[];

  @override
  Future<Map<String, dynamic>> getObj(String path, {Map<String, dynamic>? query}) async =>
      {'eligible_supply_kg': 0, 'need_kg': 500, 'note': 'Estimates only.', 'matches': <dynamic>[]};

  @override
  Future<List<Map<String, dynamic>>> getPage(String path, {Map<String, dynamic>? query}) async => [];

  @override
  Future<Map<String, dynamic>> post(String path, {Object? body, String? idempotencyKey}) async {
    posts.add(path);
    return {'id': 'd1', 'status': 'cancelled'};
  }
}

void main() {
  testWidgets('an open demand can be withdrawn after confirming, once', (tester) async {
    SharedPreferences.setMockInitialValues({});
    final api = _FakeApi();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [apiProvider.overrideWithValue(api), tokenStoreProvider.overrideWithValue(_NoTokens())],
        child: const MaterialApp(
          home: DemandDetailScreen(
            demand: {'id': 'd1', 'status': 'open', 'crop_name': 'Ragi', 'quantity_kg': 500},
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Ragi · 500 kg'), findsOneWidget);
    await tester.tap(find.text('Withdraw this demand'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Keep'));
    await tester.pumpAndSettle();
    expect(api.posts, isEmpty);
    await tester.tap(find.text('Withdraw this demand'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Withdraw'));
    await tester.pumpAndSettle();
    expect(api.posts, ['/buyer-demands/d1/cancel']);
    expect(find.text('This demand was withdrawn'), findsOneWidget);
    expect(find.text('Create pool'), findsNothing);
  });
}
