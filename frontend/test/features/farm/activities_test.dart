import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:harvestique/core/network/api_client.dart';
import 'package:harvestique/core/storage/offline_cache.dart';
import 'package:harvestique/core/storage/token_store.dart';
import 'package:harvestique/features/farm/activities_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _NoTokens extends TokenStore {
  @override
  Future<String?> access() async => null;

  @override
  Future<String?> refresh() async => null;
}

class _FakeApi extends ApiClient {
  _FakeApi() : super(tokens: _NoTokens(), cache: OfflineCache());

  List<Map<String, dynamic>> items = [
    {'id': 'a1', 'activity_type': 'irrigation', 'activity_date': '2026-10-12', 'crop_cycle_id': 'c1', 'description': 'drip'},
  ];
  final calls = <(String, String, Object?)>[];
  Completer<void>? slow;

  @override
  Future<Map<String, dynamic>> getObj(String path, {Map<String, dynamic>? query}) async =>
      {'items': items, 'total': items.length};

  @override
  Future<List<Map<String, dynamic>>> getPage(String path, {Map<String, dynamic>? query}) async => [
        {'id': 'c1', 'crop_name': 'Ragi', 'status': 'growing', 'sowing_date': '2026-08-01'},
      ];

  @override
  Future<Map<String, dynamic>> post(String path, {Object? body, String? idempotencyKey}) async {
    calls.add(('POST', path, body));
    if (slow != null) await slow!.future;
    items = [...items, {'id': 'a2', ...(body! as Map<String, dynamic>)}];
    return items.last;
  }

  @override
  Future<Map<String, dynamic>> patch(String path, Map<String, dynamic> body) async {
    calls.add(('PATCH', path, body));
    return body;
  }

  @override
  Future<void> delete(String path) async {
    calls.add(('DELETE', path, null));
    items = items.where((a) => !path.endsWith(a['id'] as String)).toList();
  }
}

Future<_FakeApi> _pump(WidgetTester tester) async {
  SharedPreferences.setMockInitialValues({});
  final api = _FakeApi();
  await tester.pumpWidget(
    ProviderScope(
      overrides: [apiProvider.overrideWithValue(api), tokenStoreProvider.overrideWithValue(_NoTokens())],
      child: const MaterialApp(home: ActivitiesScreen(farmId: 'f1')),
    ),
  );
  await tester.pumpAndSettle();
  return api;
}

Future<void> _tapSave(WidgetTester tester) async {
  await tester.dragUntilVisible(find.text('Save'), find.byType(ListView).last, const Offset(0, -200));
  await tester.pumpAndSettle();
  await tester.tap(find.text('Save'));
  await tester.pumpAndSettle();
}

void main() {
  test('validation: work type required, no future dates', () {
    final today = DateTime(2026, 10, 13);
    expect(validateActivity(type: null, date: today, today: today), 'Choose what work was done.');
    expect(validateActivity(type: 'weeding', date: DateTime(2026, 10, 14), today: today), contains('future'));
    expect(validateActivity(type: 'weeding', date: today, today: today), isNull);
  });

  testWidgets('list shows the work and the crop; add saves once', (tester) async {
    final api = await _pump(tester);
    expect(find.text('Irrigation'), findsOneWidget);
    expect(find.textContaining('Ragi · drip'), findsOneWidget);
    await tester.tap(find.text('Add field work'));
    await tester.pumpAndSettle();
    await _tapSave(tester);
    await tester.scrollUntilVisible(find.text('Choose what work was done.'), -200, scrollable: find.byType(Scrollable).last);
    expect(find.text('Choose what work was done.'), findsOneWidget);
    await tester.tap(find.text('Weeding'));
    api.slow = Completer<void>();
    await tester.dragUntilVisible(find.text('Save'), find.byType(ListView).last, const Offset(0, -200));
    await tester.tap(find.text('Save'));
    await tester.pump();
    await tester.tap(find.text('Saving…'), warnIfMissed: false);
    api.slow!.complete();
    await tester.pumpAndSettle();
    expect(api.calls.where((c) => c.$1 == 'POST'), hasLength(1));
    expect((api.calls.single.$3! as Map)['activity_type'], 'weeding');
    expect(find.text('Weeding'), findsOneWidget); // back on the refreshed list
  });

  testWidgets('edit sends a PATCH; delete asks first', (tester) async {
    final api = await _pump(tester);
    await tester.tap(find.text('Irrigation'));
    await tester.pumpAndSettle();
    expect(find.text('Edit field work'), findsOneWidget);
    await _tapSave(tester);
    expect(api.calls.single.$1, 'PATCH');
    expect(api.calls.single.$2, '/activities/a1');
    await tester.tap(find.byTooltip('Delete'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Keep'));
    await tester.pumpAndSettle();
    expect(api.calls.where((c) => c.$1 == 'DELETE'), isEmpty);
    await tester.tap(find.byTooltip('Delete'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Delete'));
    await tester.pumpAndSettle();
    expect(api.calls.last.$2, '/activities/a1');
    expect(find.text('Irrigation'), findsNothing);
  });
}
