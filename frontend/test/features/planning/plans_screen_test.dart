import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:harvestique/core/network/api_client.dart';
import 'package:harvestique/core/storage/offline_cache.dart';
import 'package:harvestique/core/storage/token_store.dart';
import 'package:harvestique/features/planning/plans_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _NoTokens extends TokenStore {
  @override
  Future<String?> access() async => null;

  @override
  Future<String?> refresh() async => null;
}

/// API double for one plan (p1). Records every request so the tests can check what the screens ask for.
class _FakeApi extends ApiClient {
  _FakeApi(this.plan) : super(tokens: _NoTokens(), cache: OfflineCache());

  Map<String, dynamic> plan;
  final gets = <String>[];
  final posts = <(String, Object?)>[];

  @override
  Future<Map<String, dynamic>> getObj(String path, {Map<String, dynamic>? query}) async {
    gets.add(path);
    if (path == '/crop-plans/p1') return plan;
    if (path == '/crop-plans/p1/evaluation') return _evaluation;
    if (path == '/farms/farm-1') return {'id': 'farm-1', 'name': 'Green Acres', 'total_area_acres': 10};
    if (path == '/farms/farm-1/expenses') {
      return {
        'items': [
          {'amount': 30000, 'category': 'seed'},
          {'amount': 13500.5, 'category': 'labour'},
        ],
        'total': 2,
      };
    }
    throw StateError('unexpected GET $path');
  }

  @override
  Future<List<Map<String, dynamic>>> getAll(String path, {Map<String, dynamic>? query, int maxItems = 1000}) =>
      getPage(path, query: query);

  @override
  Future<List<Map<String, dynamic>>> getPage(String path, {Map<String, dynamic>? query}) async {
    gets.add(path);
    return switch (path) {
      '/crops' => [
          {'id': 'crop-tomato', 'name': 'Tomato', 'local_name': 'ಟೊಮೆಟೊ', 'typical_duration_days': 120},
        ],
      _ => <Map<String, dynamic>>[],
    };
  }

  @override
  Future<Map<String, dynamic>> post(String path, {Object? body, String? idempotencyKey}) async {
    posts.add((path, body));
    return {'id': 'item-new'};
  }
}

final _tomato = <String, dynamic>{
  'id': 'item-1',
  'crop_id': null,
  'crop_name': 'Tomato',
  'area_acres': 2,
  'sowing_date': '2026-11-01',
  'duration_days': 100,
  'yield_per_acre_kg': {'low': 8000, 'expected': 12000, 'high': 16000},
  'price_per_kg': {'low': 8, 'expected': 12, 'high': 18},
  'cost': {'seed_per_acre': 4000},
  'declared_risk': 'medium',
  'estimate_basis': 'local_knowledge',
  'notes': null,
};

/// The engine's answer for the worked tomato example (see backend tests/planning_factory.py).
final _evaluation = <String, dynamic>{
  'feasible': true,
  'totals': {
    'area_sown_acres': 2,
    'cost': {'low': 87000, 'expected': 87000, 'high': 95700},
    'revenue': {'low': 128000, 'expected': 288000, 'high': 576000},
    'margin': {'low': 32300, 'expected': 201000, 'high': 489000},
  },
  'items': [
    {
      'revenue': {'expected': 288000},
      'cost': {'expected': 87000},
      'margin': {'expected': 201000},
    },
  ],
  'findings': <dynamic>[],
  'confidence': {'score': 55, 'level': 'medium'},
  'risk': {'score': 44.3, 'level': 'medium'},
};

Map<String, dynamic> _plan({List<Map<String, dynamic>> items = const [], String? farmId}) => {
      'id': 'p1',
      'name': 'Kharif 2026',
      'season': 'kharif',
      'available_land_acres': 5,
      'farm_id': farmId,
      'budget_inr': null,
      'items': items,
    };

Widget _app(ApiClient api) => ProviderScope(
      overrides: [apiProvider.overrideWithValue(api)],
      child: const MaterialApp(home: PlanDetailScreen(planId: 'p1', name: 'Kharif 2026')),
    );

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets('an empty plan asks for crops instead of showing an evaluation error', (tester) async {
    final api = _FakeApi(_plan());
    await tester.pumpWidget(_app(api));
    await tester.pumpAndSettle();
    expect(find.textContaining('No crops in this plan yet'), findsOneWidget);
    expect(find.text('Add crop'), findsOneWidget);
    expect(api.gets, isNot(contains('/crop-plans/p1/evaluation'))); // the server would answer 409
    expect(find.textContaining('Link the plan to a farm'), findsOneWidget);
  });

  testWidgets('a plan with crops shows estimated totals and actual expenses, labelled apart', (tester) async {
    final api = _FakeApi(_plan(items: [_tomato], farmId: 'farm-1'));
    await tester.pumpWidget(_app(api));
    await tester.pumpAndSettle();

    expect(find.text('Estimated net income'), findsOneWidget);
    expect(find.text('₹201,000'), findsOneWidget); // expected margin
    expect(find.text('Range: ₹32,300 to ₹489,000'), findsOneWidget);
    expect(find.text('₹128,000 / ₹288,000 / ₹576,000'), findsOneWidget);
    expect(find.text('₹87,000 / ₹95,700'), findsOneWidget);
    expect(find.text('Estimate'), findsWidgets);

    expect(find.text('Actual so far'), findsOneWidget);
    expect(find.text('Actual (recorded)'), findsOneWidget);
    expect(find.text('₹43,500.50'), findsOneWidget); // 30,000 + 13,500.50 of recorded expenses
    expect(find.text('Expenses recorded since 1 Nov 2026'), findsOneWidget);
    expect(find.textContaining('Actual sale income is not recorded'), findsOneWidget);
    expect(find.text('Farm: Green Acres'), findsOneWidget);
  });

  testWidgets('adding a crop with my own numbers posts the full entry', (tester) async {
    final api = _FakeApi(_plan());
    await tester.pumpWidget(_app(api));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Add crop'));
    await tester.pumpAndSettle();
    expect(find.text('Add crop to plan'), findsOneWidget);

    final form = find.byType(Scrollable).first;
    Future<void> fill(Finder field, String text) async {
      await tester.scrollUntilVisible(field.hitTestable(), 100, scrollable: form);
      await tester.enterText(field, text);
      await tester.pump();
    }

    await fill(find.widgetWithText(TextField, 'Crop name'), 'Beans');
    await fill(find.widgetWithText(TextField, 'Area (acres)'), '1.5');
    await tester.tap(find.text('Sowing date'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('OK'));
    await tester.pumpAndSettle();
    await fill(find.widgetWithText(TextField, 'Days from sowing to harvest'), '75');
    await fill(find.byKey(const Key('yield-low')), '3000');
    await fill(find.byKey(const Key('yield-expected')), '4000');
    await fill(find.byKey(const Key('yield-high')), '5000');
    await fill(find.byKey(const Key('price-low')), '20');
    await fill(find.byKey(const Key('price-expected')), '30');
    await fill(find.byKey(const Key('price-high')), '40');
    await fill(find.widgetWithText(TextField, 'Seed (₹ per acre)'), '2500');
    final save = find.text('Add to plan');
    await tester.scrollUntilVisible(save.hitTestable(), 200, scrollable: form);
    await tester.tap(save);
    await tester.pumpAndSettle();

    expect(api.posts, hasLength(1));
    final (path, body) = api.posts.single;
    expect(path, '/crop-plans/p1/items');
    final m = body! as Map<String, dynamic>;
    expect(m['crop_name'], 'Beans');
    expect(m.containsKey('crop_id'), isFalse);
    expect(m['area_acres'], 1.5);
    expect(m['duration_days'], 75);
    expect(m['yield_per_acre_kg'], {'low': 3000.0, 'expected': 4000.0, 'high': 5000.0});
    expect(m['price_per_kg'], {'low': 20.0, 'expected': 30.0, 'high': 40.0});
    expect(m['cost'], {'seed_per_acre': 2500.0});
    expect(m['estimate_basis'], 'local_knowledge');
    expect(find.text('Add crop to plan'), findsNothing); // closed, and the plan reloaded
  });

  testWidgets('a problem in the crop form is shown and nothing is sent', (tester) async {
    final api = _FakeApi(_plan());
    await tester.pumpWidget(_app(api));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Add crop'));
    await tester.pumpAndSettle();
    final form = find.byType(Scrollable).first;
    final save = find.text('Add to plan');
    await tester.scrollUntilVisible(save.hitTestable(), 200, scrollable: form);
    await tester.tap(save);
    await tester.pumpAndSettle();
    expect(api.posts, isEmpty);
    await tester.scrollUntilVisible(find.textContaining('Choose a crop').hitTestable(), -200, scrollable: form);
    expect(find.textContaining('Choose a crop, or type the crop name.'), findsOneWidget);
  });
}
