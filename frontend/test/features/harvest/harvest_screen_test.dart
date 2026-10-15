import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:harvestique/core/errors/app_failure.dart';
import 'package:harvestique/core/network/api_client.dart';
import 'package:harvestique/core/storage/offline_cache.dart';
import 'package:harvestique/core/storage/token_store.dart';
import 'package:harvestique/features/harvest/harvest_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _NoTokens extends TokenStore {
  @override
  Future<String?> access() async => null;

  @override
  Future<String?> refresh() async => null;
}

Map<String, dynamic> _lot({bool offered = false}) => {
      'id': 'lot-1',
      'crop_cycle_id': 'c1',
      'status': 'open',
      'crop_name': 'Tomato',
      'plot_name': 'Plot 1',
      'farm_name': 'Green Acres',
      'sowing_date': '2026-08-01',
      'committable_kg': 900,
      'committed_kg': 300,
      'available_kg': 600,
      'shortfall_kg': 0,
      'basis': 'Pessimistic (p10) prediction.',
      'pool_eligible': offered,
      'expected_grade': 'B',
    };

class _FakeApi extends ApiClient {
  _FakeApi() : super(tokens: _NoTokens(), cache: OfflineCache());

  Map<String, dynamic> lot = _lot();
  final patches = <Map<String, dynamic>>[];
  Completer<void>? slow;
  AppFailure? failWith;

  @override
  Future<List<Map<String, dynamic>>> getPage(String path, {Map<String, dynamic>? query}) async {
    if (path == '/inventory/lots') return [lot];
    return [
      {
        'order_id': 'a1b2c3d4-0000-0000-0000-000000000000',
        'crop_name': 'Tomato',
        'quantity_kg': 300,
        'fulfilled_kg': 0,
        'window_end': '2026-11-20',
        'progress': 'preparing',
      },
    ];
  }

  @override
  Future<Map<String, dynamic>> patch(String path, Map<String, dynamic> body) async {
    patches.add(body);
    if (slow != null) await slow!.future;
    if (failWith != null) throw failWith!;
    lot = {...lot, ...body};
    return lot;
  }
}

Future<_FakeApi> _pump(WidgetTester tester, {Map<String, dynamic>? lot}) async {
  SharedPreferences.setMockInitialValues({});
  final api = _FakeApi();
  if (lot != null) api.lot = lot;
  await tester.pumpWidget(
    ProviderScope(
      overrides: [apiProvider.overrideWithValue(api), tokenStoreProvider.overrideWithValue(_NoTokens())],
      child: const MaterialApp(home: Scaffold(body: HarvestScreen())),
    ),
  );
  await tester.pumpAndSettle();
  return api;
}

void main() {
  test('lot title names the crop, plot and farm', () {
    expect(lotTitle(_lot()), 'Tomato · Plot 1, Green Acres');
    expect(lotTitle({'crop_name': 'Ragi'}), 'Ragi');
  });

  testWidgets('a lot says which crop it is; deliveries show the order number and progress', (tester) async {
    await _pump(tester);
    expect(find.text('Tomato · Plot 1, Green Acres'), findsOneWidget);
    expect(find.textContaining('#A1B2C3D4 · Tomato'), findsOneWidget);
    expect(find.textContaining('Preparing'), findsOneWidget);
  });

  testWidgets('offering to buyers is sent once, even when tapped twice', (tester) async {
    final api = await _pump(tester);
    api.slow = Completer<void>();
    await tester.tap(find.byType(Switch));
    await tester.pump();
    await tester.tap(find.byType(Switch));
    await tester.pump();
    expect(find.text('Saving…'), findsOneWidget);
    api.slow!.complete();
    await tester.pumpAndSettle();
    expect(api.patches, [
      {'pool_eligible': true},
    ]);
    expect(find.text('Offered to buyers.'), findsOneWidget);
    expect(tester.widget<Switch>(find.byType(Switch)).value, isTrue);
  });

  testWidgets('a failed change shows the reason and leaves the switch as it was', (tester) async {
    final api = await _pump(tester);
    api.failWith = const AppFailure('network', 'Cannot reach the Harvestique server.');
    await tester.tap(find.byType(Switch));
    await tester.pumpAndSettle();
    expect(find.text('Cannot reach the Harvestique server.'), findsOneWidget);
    expect(tester.widget<Switch>(find.byType(Switch)).value, isFalse);
  });

  testWidgets('predicted, promised, reserved, confirmed, harvested and delivered quantities are shown apart', (tester) async {
    tester.view.physicalSize = const Size(1080, 3000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await _pump(
      tester,
      lot: {
        ..._lot(),
        'p50_kg': 1200,
        'awaiting_confirmation_kg': 100,
        'confirmed_kg': 200,
        'fulfilled_kg': 0,
      },
    );
    expect(find.text('Predicted harvest (most likely)'), findsOneWidget);
    expect(find.text('1,200 kg'), findsOneWidget);
    expect(find.text('… requested, awaiting your answer'), findsOneWidget);
    expect(find.text('… confirmed by you'), findsOneWidget);
    expect(find.text('… delivered'), findsOneWidget);
    expect(find.text('Harvested (weighed)'), findsNothing); // a prediction is never shown as harvested produce
    expect(find.textContaining('update the prediction'), findsOneWidget);
  });

  testWidgets('after harvest the weighed quantity is shown, not the prediction', (tester) async {
    await _pump(tester, lot: {..._lot(), 'status': 'harvested', 'p50_kg': 1200, 'actual_kg': 950});
    expect(find.text('Harvested (weighed)'), findsOneWidget);
    expect(find.text('950 kg'), findsOneWidget);
    expect(find.text('Predicted harvest (most likely)'), findsNothing);
    expect(find.text('… confirmed by you'), findsNothing); // an older server sends no split: nothing invented
  });
}
