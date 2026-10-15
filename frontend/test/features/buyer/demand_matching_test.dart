import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:harvestique/core/network/api_client.dart';
import 'package:harvestique/core/storage/offline_cache.dart';
import 'package:harvestique/core/storage/token_store.dart';
import 'package:harvestique/features/buyer/demands_screen.dart';
import 'package:harvestique/features/buyer/supply_status.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _NoTokens extends TokenStore {
  @override
  Future<String?> access() async => null;

  @override
  Future<String?> refresh() async => null;
}

/// The seven-farmer example: tomato farmers A 150, B 200 and F 100 kg (450 kg) against a 500 kg hotel demand.
/// Onion, potato, chilli and cabbage farmers are never part of a tomato result (the server filters by crop).
Map<String, dynamic> sevenFarmerMatches() => {
      'demand_id': 'd1',
      'need_kg': 500,
      'eligible_supply_kg': 450,
      'shortfall_kg': 50,
      'shortage_kg': 50,
      'fulfilment': 'partial',
      'eligible_count': 3,
      'excluded_reasons': {'window_no_overlap': 1},
      'explanation': [
        'Only Tomato supply is considered; other crops are never matched.',
        'Needed 500 kg; eligible predicted supply 450 kg from 3 farms (pessimistic p10 estimates, not harvested produce).',
        'Shortage 50 kg: current predictions cannot cover the whole demand.',
      ],
      'next_steps': ['create_pool', 'wait_for_supply', 'revise_dates', 'choose_other_crop'],
      'note': 'Quantities are p10-based (pessimistic).',
      'matches': [
        for (final (ref, kgs) in [('farm-a', 150), ('farm-b', 200), ('farm-f', 100)])
          {
            'lot_id': '$ref-lot',
            'farm_ref': ref,
            'eligible': true,
            'reasons': <String>[],
            'score': 70,
            'components': <String, dynamic>{},
            'available_kg': kgs,
            'window_start': '2026-11-01',
            'window_end': '2026-11-20',
            'confidence': 60,
            'risk': 20,
            'reliability': 0.5,
          },
        {
          'lot_id': 'late-lot',
          'farm_ref': 'farm-h',
          'eligible': false,
          'reasons': ['window_no_overlap'],
          'score': 40,
          'components': <String, dynamic>{},
          'available_kg': 80,
          'window_start': '2027-01-01',
          'window_end': '2027-01-10',
          'confidence': 60,
          'risk': 20,
          'reliability': 0.5,
        },
      ],
    };

class _FakeApi extends ApiClient {
  _FakeApi({required this.matches, this.demand = const {}, this.demands = const [], this.pools = const []})
      : super(tokens: _NoTokens(), cache: OfflineCache());

  final Map<String, dynamic> matches;
  final Map<String, dynamic> demand;
  final List<Map<String, dynamic>> demands;
  final List<Map<String, dynamic>> pools;
  final posts = <String>[];

  @override
  Future<Map<String, dynamic>> getObj(String path, {Map<String, dynamic>? query}) async =>
      path.endsWith('/matches') ? matches : demand;

  @override
  Future<List<Map<String, dynamic>>> getPage(String path, {Map<String, dynamic>? query}) async =>
      path == '/buyer-demands' ? demands : (path == '/pools' ? pools : []);

  @override
  Future<Map<String, dynamic>> post(String path, {Object? body, String? idempotencyKey}) async {
    posts.add(path);
    return {'id': 'p1'};
  }
}

const _tomatoDemand = {'id': 'd1', 'status': 'open', 'crop_name': 'Tomato', 'quantity_kg': 500};

Future<_FakeApi> _pumpDetail(WidgetTester tester, _FakeApi api) async {
  SharedPreferences.setMockInitialValues({});
  tester.view.physicalSize = const Size(1080, 4000); // the whole screen at once: no scrolling in the test
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    ProviderScope(
      overrides: [apiProvider.overrideWithValue(api), tokenStoreProvider.overrideWithValue(_NoTokens())],
      child: const MaterialApp(home: DemandDetailScreen(demand: _tomatoDemand)),
    ),
  );
  await tester.pumpAndSettle();
  return api;
}

void main() {
  group('matching arithmetic and words', () {
    test('the seven-farmer example is a partial match with a 50 kg shortage', () {
      final m = sevenFarmerMatches();
      expect(fulfilmentOf(m), 'partial');
      expect(shortageOf(m), 50);
    });

    test('an older server without the summary fields is worked out from the same numbers', () {
      expect(fulfilmentOf({'need_kg': 500, 'eligible_supply_kg': 450, 'shortfall_kg': 50}), 'partial');
      expect(fulfilmentOf({'need_kg': 500, 'eligible_supply_kg': 600, 'shortfall_kg': 0}), 'full');
      expect(fulfilmentOf({'need_kg': 500, 'eligible_supply_kg': 0, 'shortfall_kg': 500}), 'none');
      // the schema's default "none" is not trusted when there is eligible supply
      expect(fulfilmentOf({'fulfilment': 'none', 'need_kg': 500, 'eligible_supply_kg': 450}), 'partial');
      expect(shortageOf({'need_kg': 500, 'eligible_supply_kg': 450}), 50);
      expect(shortageOf({'need_kg': 500, 'eligible_supply_kg': 700}), 0);
      expect(shortageOf({'shortage_kg': -3}), 0);
    });

    test('every server reason and next step has plain words; unknown codes are still shown', () {
      for (final code in [
        'crop_mismatch',
        'grade_below_minimum',
        'not_opted_in',
        'lot_not_open',
        'no_available_quantity',
        'window_no_overlap',
        'confidence_below_minimum',
        'risk_above_maximum',
        'location_unknown',
        'too_far',
      ]) {
        expect(reasonText(code), isNot(contains('_')), reason: code);
      }
      for (final step in [
        'create_pool',
        'wait_for_supply',
        'revise_dates',
        'widen_distance',
        'accept_lower_grade',
        'relax_risk_limits',
        'choose_other_crop',
      ]) {
        expect(nextStepText(step), isNot(contains('_')), reason: step);
      }
      expect(reasonText('new_reason'), 'New reason');
      expect(nextStepText('choose_other_crop'), contains('never substitutes'));
    });

    test('every demand stage has a buyer-facing title; older servers fall back to the status', () {
      const titles = {
        'open': 'Open: nothing reserved yet',
        'matching_supply_available': 'Matching supply available',
        'supply_reserved': 'Matching supply reserved',
        'partially_matched': 'Partially matched: shortage remaining',
        'no_matching_supply': 'No matching supply available',
        'awaiting_farmer_confirmation': 'Awaiting farmer confirmation',
        'confirmed': 'Confirmed',
        'reallocation_required': 'Supply changed: reallocation required',
        'in_fulfilment': 'In fulfilment',
        'fulfilled': 'Fulfilled',
        'partially_fulfilled': 'Partially fulfilled',
        'cancelled': 'Cancelled',
      };
      titles.forEach((stage, title) => expect(demandStage({'stage': stage}).title, title));
      expect(demandStage({'status': 'pooled'}).title, 'Matching supply reserved');
      expect(demandStage({'status': 'cancelled'}).title, 'Cancelled');
      expect(demandStage({'status': 'open'}).title, 'Open: nothing reserved yet');
    });

    test('a demand shortage is the uncovered quantity, and none once the demand is closed', () {
      expect(demandShortage({'stage': 'partially_matched', 'shortage_kg': 50}), 50);
      expect(demandShortage({'stage': 'reallocation_required', 'remaining_kg': 70, 'shortage_kg': 0}), 70);
      expect(demandShortage({'stage': 'cancelled', 'remaining_kg': 70}), 0);
      expect(demandShortage({'status': 'open'}), 0);
    });

    test('the maximum delivery distance must be a positive number of km', () {
      expect(validateMaxDistance('100'), isNull);
      expect(validateMaxDistance('0'), isNotNull);
      expect(validateMaxDistance('abc'), isNotNull);
      expect(validateMaxDistance('5000'), isNotNull);
    });
  });

  testWidgets('seven farmers: the tomato demand shows 450 kg eligible, a 50 kg shortage and why', (tester) async {
    await _pumpDetail(tester, _FakeApi(matches: sevenFarmerMatches(), demand: {..._tomatoDemand, 'stage': 'partially_matched'}));
    expect(find.text('Partially matched: shortage remaining'), findsWidgets);
    expect(find.text('450 kg · 3 farm lots'), findsOneWidget);
    expect(find.text('50 kg'), findsOneWidget); // the shortage row
    expect(find.text('Only Tomato supply is considered; other crops are never matched.'), findsOneWidget);
    expect(find.text('• 1 · harvest dates do not fit your delivery window'), findsOneWidget);
    expect(find.textContaining('never substitutes a crop'), findsOneWidget);
    expect(find.text('Create pool for the available 450 kg'), findsOneWidget);
    expect(find.text('Farm farm-a · 150 kg'), findsOneWidget);
    expect(find.text('Farm farm-b · 200 kg'), findsOneWidget);
    expect(find.text('Farm farm-f · 100 kg'), findsOneWidget);
  });

  testWidgets('no matching supply: nothing can be reserved, the demand stays open and can be withdrawn', (tester) async {
    final api = await _pumpDetail(
      tester,
      _FakeApi(
        matches: {
          'need_kg': 500,
          'eligible_supply_kg': 0,
          'shortfall_kg': 500,
          'shortage_kg': 500,
          'fulfilment': 'none',
          'eligible_count': 0,
          'next_steps': ['wait_for_supply', 'choose_other_crop'],
          'note': '',
          'matches': <dynamic>[],
        },
        demand: {..._tomatoDemand, 'stage': 'no_matching_supply'},
      ),
    );
    expect(find.text('No matching supply available'), findsWidgets);
    expect(find.textContaining('no pool can be created'), findsOneWidget);
    expect(find.textContaining('Create pool'), findsNothing);
    expect(find.text('Withdraw this demand'), findsOneWidget);
    expect(find.textContaining('Keep the demand open'), findsOneWidget);
    expect(api.posts, isEmpty);
  });

  testWidgets('full supply: the pool reserves only what is needed, sent once with an idempotency key', (tester) async {
    final api = await _pumpDetail(
      tester,
      _FakeApi(
        matches: {
          'need_kg': 500,
          'eligible_supply_kg': 650,
          'shortfall_kg': 0,
          'shortage_kg': 0,
          'fulfilment': 'full',
          'eligible_count': 4,
          'next_steps': ['create_pool'],
          'note': '',
          'matches': <dynamic>[],
        },
      ),
    );
    expect(find.text('Matching supply available'), findsOneWidget);
    expect(find.text('none'), findsOneWidget); // shortage
    expect(find.textContaining('reserves only the 500 kg you need'), findsOneWidget);
    await tester.tap(find.text('Create pool'));
    await tester.pumpAndSettle();
    expect(api.posts, ['/buyer-demands/d1/pool']);
  });

  testWidgets('an older server without the summary still shows the shortage honestly', (tester) async {
    await _pumpDetail(
      tester,
      _FakeApi(matches: {'need_kg': 500, 'eligible_supply_kg': 450, 'shortfall_kg': 50, 'eligible_count': 3, 'note': ''}),
    );
    expect(find.text('Partially matched: shortage remaining'), findsOneWidget);
    expect(find.text('50 kg'), findsOneWidget);
    expect(find.text('Open: nothing reserved yet'), findsOneWidget); // no stage from the server: from the status
  });

  testWidgets('the latest stage from the server is shown: supply changed after a prediction fell', (tester) async {
    await _pumpDetail(
      tester,
      _FakeApi(
        matches: {'need_kg': 70, 'eligible_supply_kg': 0, 'shortfall_kg': 70, 'fulfilment': 'none', 'note': ''},
        demand: {..._tomatoDemand, 'status': 'pooled', 'stage': 'reallocation_required', 'remaining_kg': 70},
        pools: [
          {'id': 'p1', 'demand_id': 'd1', 'status': 'at_risk', 'demand_kg': 500, 'allocated_kg': 430, 'unfilled_kg': 70},
        ],
      ),
    );
    expect(find.text('Supply changed: reallocation required'), findsOneWidget);
    expect(find.text('Supply for the part still needed'), findsOneWidget);
    expect(find.text('430 kg of 500 kg allocated · 70 kg not yet covered'), findsOneWidget);
    expect(find.textContaining('Create pool'), findsNothing); // the pool exists: no second one
  });

  testWidgets('the demand list shows each demand\'s stage and shortage', (tester) async {
    SharedPreferences.setMockInitialValues({});
    final api = _FakeApi(
      matches: const {},
      demands: [
        {..._tomatoDemand, 'window_start': '2026-11-01', 'window_end': '2026-11-20', 'min_grade': 'B', 'stage': 'partially_matched', 'shortage_kg': 50},
        {'id': 'd2', 'crop_name': 'Onion', 'quantity_kg': 300, 'status': 'pooled', 'stage': 'confirmed', 'remaining_kg': 0},
      ],
    );
    await tester.pumpWidget(
      ProviderScope(
        overrides: [apiProvider.overrideWithValue(api), tokenStoreProvider.overrideWithValue(_NoTokens())],
        child: const MaterialApp(home: Scaffold(body: DemandsScreen())),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Partially matched: shortage remaining'), findsOneWidget);
    expect(find.text('Short by 50 kg'), findsOneWidget);
    expect(find.text('Confirmed'), findsOneWidget);
  });
}
