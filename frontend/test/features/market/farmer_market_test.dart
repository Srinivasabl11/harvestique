import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:harvestique/core/network/api_client.dart';
import 'package:harvestique/core/storage/offline_cache.dart';
import 'package:harvestique/core/storage/token_store.dart';
import 'package:harvestique/features/market/farmer_market_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _NoTokens extends TokenStore {
  @override
  Future<String?> access() async => null;

  @override
  Future<String?> refresh() async => null;
}

Map<String, dynamic> _part(String id, String status, {String? progress}) => {
      'id': id,
      'status': status,
      'item_status': status == 'pending' ? 'awaiting_farmer' : status,
      'order_id': 'a1b2c3d4-0000-0000-0000-000000000000',
      'order_status': 'confirmed',
      'crop_name': 'Tomato',
      'quantity_kg': 300,
      'buyer_business': 'Rao Fresh Mart',
      'buyer_type': 'retailer',
      'window_start': '2026-11-01',
      'window_end': '2026-11-20',
      'min_grade': 'B',
      'progress': progress,
    };

class _FakeApi extends ApiClient {
  _FakeApi(this.parts) : super(tokens: _NoTokens(), cache: OfflineCache());

  List<Map<String, dynamic>> parts;
  final posts = <(String, Object?)>[];
  Completer<void>? slow;

  @override
  Future<List<Map<String, dynamic>>> getList(String path, {Map<String, dynamic>? query}) async => [];

  @override
  Future<List<Map<String, dynamic>>> getPage(String path, {Map<String, dynamic>? query}) async => parts;

  @override
  Future<Map<String, dynamic>> post(String path, {Object? body, String? idempotencyKey}) async {
    posts.add((path, body));
    if (slow != null) await slow!.future;
    final id = path.split('/')[2];
    parts = [
      for (final p in parts)
        if (p['id'] != id)
          p
        else if (path.endsWith('/accept'))
          {...p, 'status': 'accepted', 'item_status': 'accepted'}
        else if (path.endsWith('/progress'))
          {...p, 'progress': (body! as Map)['stage']}
        else
          p,
    ];
    return {};
  }
}

Widget _app(ApiClient api) => ProviderScope(
      overrides: [apiProvider.overrideWithValue(api), tokenStoreProvider.overrideWithValue(_NoTokens())],
      child: const MaterialApp(home: Scaffold(body: FarmerMarketScreen())),
    );

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('order references match the notifications', () => expect(orderRef('a1b2c3d4-0000'), '#A1B2C3D4'));

  testWidgets('accept once, then mark preparing and ready', (tester) async {
    final api = _FakeApi([_part('p1', 'pending')]);
    await tester.pumpWidget(_app(api));
    await tester.pumpAndSettle();
    expect(find.textContaining('Order #A1B2C3D4 · Tomato'), findsOneWidget);

    api.slow = Completer<void>();
    await tester.tap(find.text('Accept'));
    await tester.pump();
    await tester.tap(find.text('Accept'), warnIfMissed: false); // a second tap while the first is running
    await tester.pump();
    api.slow!.complete();
    api.slow = null;
    await tester.pumpAndSettle();
    expect(api.posts.where((p) => p.$1.endsWith('/accept')), hasLength(1));

    expect(find.textContaining('Your accepted orders (1)'), findsOneWidget);
    await tester.tap(find.text('Mark preparing'));
    await tester.pumpAndSettle();
    expect(api.posts.last.$1, '/participations/p1/progress');
    expect(api.posts.last.$2, {'stage': 'preparing'});
    await tester.tap(find.text('Mark ready'));
    await tester.pumpAndSettle();
    expect(api.posts.last.$1, '/participations/p1/progress');
    expect(api.posts.last.$2, {'stage': 'ready'});
    expect(find.widgetWithText(Chip, 'Ready'), findsOneWidget);
    expect(find.text('Mark ready'), findsNothing);
  });
}
