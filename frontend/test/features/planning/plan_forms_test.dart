import 'package:flutter_test/flutter_test.dart';
import 'package:harvestique/features/planning/plan_forms.dart';

void main() {
  group('validateRange', () {
    String? v(String l, String e, String h) => validateRange('Yield', 'kg per acre', l, e, h);

    test('accepts low <= expected <= high', () {
      expect(v('8000', '12000', '16000'), isNull);
      expect(v('0', '5', '5'), isNull);
    });
    test('needs all three', () => expect(v('1', '', '3'), contains('enter low, expected and high')));
    test('numbers only', () => expect(v('1', 'abc', '3'), contains('numbers only')));
    test('ordered', () => expect(v('9', '5', '12'), contains('low must not be above expected')));
    test('expected above zero', () => expect(v('0', '0', '0'), contains('more than 0')));
    test('no negatives', () => expect(v('-1', '2', '3'), contains('negative')));
    test('decimal places', () {
      expect(validateRange('Price', '₹ per kg', '1.5', '2.25', '3.125', maxDecimals: 2), contains('2 digits'));
    });
  });

  group('validatePlanItem', () {
    String? v({
      String name = 'Tomato',
      String area = '2',
      DateTime? sowing,
      bool noSowing = false,
      String duration = '100',
      List<String> yieldT = const ['8000', '12000', '16000'],
      List<String> price = const ['8', '12', '18'],
      Map<String, String> cost = const {'seed_per_acre': '4000'},
      List<(String, DateTime)> others = const [],
    }) =>
        validatePlanItem(
          cropName: name,
          areaText: area,
          planLand: 5,
          sowing: noSowing ? null : (sowing ?? DateTime(2026, 11, 1)),
          durationText: duration,
          yieldTexts: yieldT,
          priceTexts: price,
          costTexts: cost,
          otherEntries: others,
        );

    test('accepts the worked tomato example', () => expect(v(), isNull));
    test('needs a crop', () => expect(v(name: '  '), contains('Choose a crop')));
    test('area must be positive', () => expect(v(area: '0'), contains('more than 0')));
    test('area cannot exceed the plan land', () => expect(v(area: '6'), contains('more than the plan')));
    test('sowing date required', () => expect(v(noSowing: true), contains('sowing date')));
    test('sowing date must be sane', () => expect(v(sowing: DateTime(1999, 1, 1)), contains('between 2000 and 2100')));
    test('duration is a whole number of days', () {
      expect(v(duration: '0'), contains('1 to 3650'));
      expect(v(duration: '12.5'), contains('1 to 3650'));
    });
    test('yield and price ranges are checked', () {
      expect(v(yieldT: const ['9', '5', '12']), startsWith('Yield'));
      expect(v(price: const ['1', '0', '2']), startsWith('Price'));
    });
    test('costs cannot be negative or non-numeric', () {
      expect(v(cost: const {'fertilizer_per_acre': '-5'}), contains('negative'));
      expect(v(cost: const {'labour_wage_per_day': 'x'}), contains('numbers only'));
    });
    test('the same crop on the same sowing date is a duplicate', () {
      expect(v(others: [('tomato', DateTime(2026, 11, 1))]), contains('already has tomato'));
      expect(v(others: [('Tomato', DateTime(2026, 12, 1))]), isNull);
      expect(v(others: [('Ragi', DateTime(2026, 11, 1))]), isNull);
    });
  });

  test('planItemBody matches the API contract (worked tomato example)', () {
    final body = planItemBody(
      cropId: 'crop-1',
      cropName: ' Tomato ',
      area: 2,
      sowing: DateTime(2026, 11, 1),
      durationDays: 100,
      yieldTexts: const ['8000', '12000', '16000'],
      priceTexts: const ['8', '12', '18'],
      costTexts: const {
        'seed_per_acre': '4000',
        'fertilizer_per_acre': '',
        'labour_person_days_per_acre': '60',
        'fixed_cost': '5,000',
      },
      risk: 'medium',
      basis: 'own_records',
    );
    expect(body, {
      'crop_id': 'crop-1',
      'crop_name': 'Tomato',
      'area_acres': 2.0,
      'sowing_date': '2026-11-01',
      'duration_days': 100,
      'yield_per_acre_kg': {'low': 8000.0, 'expected': 12000.0, 'high': 16000.0},
      'price_per_kg': {'low': 8.0, 'expected': 12.0, 'high': 18.0},
      'cost': {'seed_per_acre': 4000.0, 'labour_person_days_per_acre': 60.0, 'fixed_cost': 5000.0},
      'declared_risk': 'medium',
      'estimate_basis': 'own_records',
    });
  });

  test('fromPredictionBody sends only what the prediction cannot supply', () {
    expect(
      fromPredictionBody(predictionId: 'pred-1', priceTexts: const ['20', '25', '30'], costTexts: const {}, risk: 'low'),
      {
        'prediction_id': 'pred-1',
        'price_per_kg': {'low': 20.0, 'expected': 25.0, 'high': 30.0},
        'cost': <String, dynamic>{},
        'declared_risk': 'low',
      },
    );
  });

  group('validateNewPlan', () {
    test('accepts a named plan with land',
        () => expect(validateNewPlan(name: 'K', landText: '5', farmArea: null, budgetText: ''), isNull),);
    test(
        'needs a name', () => expect(validateNewPlan(name: '', landText: '5', farmArea: null, budgetText: ''), contains('name')),);
    test('needs land', () => expect(validateNewPlan(name: 'K', landText: '', farmArea: null, budgetText: ''), contains('land')));
    test('land within the farm', () {
      expect(validateNewPlan(name: 'K', landText: '11', farmArea: 10, budgetText: ''), contains('more than the farm'));
    });
    test('budget positive when given', () {
      expect(validateNewPlan(name: 'K', landText: '5', farmArea: null, budgetText: '0'), contains('budget'));
    });
  });
}
