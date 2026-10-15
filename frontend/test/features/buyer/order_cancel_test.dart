import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:harvestique/core/network/api_client.dart';
import 'package:harvestique/core/storage/offline_cache.dart';
import 'package:harvestique/core/storage/token_store.dart';
import 'package:harvestique/features/buyer/order_detail_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _NoTokens extends TokenStore {
  @override
  Future<String?> access() async => null;

  @override
  Future<String?> refresh() async => null;
}

class _FakeApi extends ApiClient {
  _FakeApi() : super(tokens: _NoTokens(), cache: OfflineCache());

  String status = 'confirmed';
  final posts = <String>[];

  @override
  Future<Map<String, dynamic>> getObj(String path, {Map<String, dynamic>? query}) async => {
        'id': 'a1b2c3d4-0000',
        'status': status,
        'crop_name': 'Ragi',
        'ordered_kg': 50,
        'committed_kg': 50,
        'delivered_kg': 0,
        'window_start': '2026-11-26',
        'window_end': '2027-01-25',
        'items': <dynamic>[],
      };

  @override
  Future<List<Map<String, dynamic>>> getList(String path, {Map<String, dynamic>? query}) async => [];

  @override
  Future<Map<String, dynamic>> post(String path, {Object? body, String? idempotencyKey}) async {
    posts.add(path);
    status = 'cancelled';
    return {};
  }
}

void main() {
  testWidgets('cancelling an order asks first; Keep order does nothing', (tester) async {
    SharedPreferences.setMockInitialValues({});
    final api = _FakeApi();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [apiProvider.overrideWithValue(api), tokenStoreProvider.overrideWithValue(_NoTokens())],
        child: const MaterialApp(home: OrderDetailScreen(orderId: 'a1b2c3d4-0000')),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('Cancel order'));
    await tester.pumpAndSettle();
    expect(find.text('Cancel this order?'), findsOneWidget);
    await tester.tap(find.text('Keep order'));
    await tester.pumpAndSettle();
    expect(api.posts, isEmpty);
    await tester.tap(find.text('Cancel order'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Cancel order').last);
    await tester.pumpAndSettle();
    expect(api.posts, ['/orders/a1b2c3d4-0000/cancel']);
    expect(find.textContaining('Cancelled'), findsWidgets);
  });
}
