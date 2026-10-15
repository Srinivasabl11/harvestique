/// Pure, testable rules for the income-planner forms. The server applies the same rules (and more); these give the
/// farmer the problem before anything is sent.
library;

import '../../core/util/format.dart';

const planSeasons = ['year_round', 'kharif', 'rabi', 'summer'];
const riskLevels = ['low', 'medium', 'high'];

/// Where the yield and price numbers come from (the server's EstimateBasis; it drives the confidence score).
const estimateBases = <(String, String)>[
  ('own_records', 'My own past records'),
  ('local_knowledge', 'Local knowledge (neighbours, dealers)'),
  ('assumption', 'A guess'),
];

/// Per-acre cost fields of the API's `cost` object, with their labels (all INR, all optional, 0 when empty).
const costFields = <(String, String)>[
  ('seed_per_acre', 'Seed (₹ per acre)'),
  ('fertilizer_per_acre', 'Fertilizer (₹ per acre)'),
  ('pesticide_per_acre', 'Pesticide (₹ per acre)'),
  ('irrigation_per_acre', 'Irrigation (₹ per acre)'),
  ('machinery_per_acre', 'Machinery (₹ per acre)'),
  ('other_per_acre', 'Other (₹ per acre)'),
  ('labour_person_days_per_acre', 'Labour (person-days per acre)'),
  ('labour_wage_per_day', 'Labour wage (₹ per day)'),
  ('fixed_cost', 'Fixed cost for this crop (₹, not per acre)'),
];

/// A parsed number, or null when empty. Throws [FormatException] text for anything that is not a number.
double? parseNumber(String text) {
  final t = text.trim().replaceAll(',', '');
  if (t.isEmpty) return null;
  final v = double.tryParse(t);
  if (v == null) throw const FormatException('not a number');
  return v;
}

int _decimals(String text) {
  final t = text.trim();
  final dot = t.indexOf('.');
  return dot < 0 ? 0 : t.length - dot - 1;
}

/// low <= expected <= high, all present, none negative, expected > 0, at most [maxDecimals] decimals.
String? validateRange(String what, String unit, String low, String expected, String high, {int maxDecimals = 3}) {
  final List<double?> v;
  try {
    v = [parseNumber(low), parseNumber(expected), parseNumber(high)];
  } on FormatException {
    return '$what: use numbers only ($unit).';
  }
  if (v.any((x) => x == null)) return '$what: enter low, expected and high ($unit).';
  final l = v[0]!, e = v[1]!, h = v[2]!;
  if (l < 0 || h < 0) return '$what cannot be negative.';
  if (e <= 0) return '$what: the expected value must be more than 0.';
  if (!(l <= e && e <= h)) return '$what: low must not be above expected, and expected not above high.';
  if ([low, expected, high].any((t) => _decimals(t) > maxDecimals)) {
    return '$what: use at most $maxDecimals digits after the decimal point.';
  }
  return null;
}

/// Everything the add/edit crop form checks before sending. Returns the first problem, or null.
String? validatePlanItem({
  required String cropName,
  required String areaText,
  required double planLand,
  required DateTime? sowing,
  required String durationText,
  required List<String> yieldTexts,
  required List<String> priceTexts,
  required Map<String, String> costTexts,
  required List<(String, DateTime)> otherEntries,
}) {
  if (cropName.trim().isEmpty) return 'Choose a crop, or type the crop name.';
  if (cropName.trim().length > 80) return 'The crop name is too long (80 characters at most).';
  final double? area;
  try {
    area = parseNumber(areaText);
  } on FormatException {
    return 'Area: use a number of acres.';
  }
  if (area == null || area <= 0) return 'Enter the area in acres (more than 0).';
  if (_decimals(areaText) > 3) return 'Area: use at most 3 digits after the decimal point.';
  if (area > planLand) return 'The area (${number(area)} acres) is more than the plan\'s land (${number(planLand)} acres).';
  if (sowing == null) return 'Choose the sowing date.';
  if (sowing.year < 2000 || sowing.year > 2100) return 'The sowing date must be between 2000 and 2100.';
  final int? duration = int.tryParse(durationText.trim());
  if (duration == null || duration < 1 || duration > 3650) {
    return 'Days from sowing to harvest: a whole number from 1 to 3650.';
  }
  final y = validateRange('Yield', 'kg per acre', yieldTexts[0], yieldTexts[1], yieldTexts[2]);
  if (y != null) return y;
  final p = validateRange('Price', '₹ per kg', priceTexts[0], priceTexts[1], priceTexts[2], maxDecimals: 2);
  if (p != null) return p;
  final c = validateCosts(costTexts);
  if (c != null) return c;
  final key = cropName.trim().toLowerCase();
  final day0 = DateTime(sowing.year, sowing.month, sowing.day);
  for (final (name, date) in otherEntries) {
    if (name.trim().toLowerCase() == key && DateTime(date.year, date.month, date.day) == day0) {
      return 'This plan already has ${name.trim()} sown on ${day(isoDate(day0))}. Edit that entry or choose another date.';
    }
  }
  return null;
}

String? validateCosts(Map<String, String> costTexts) {
  for (final (key, labelText) in costFields) {
    final text = costTexts[key] ?? '';
    final double? v;
    try {
      v = parseNumber(text);
    } on FormatException {
      return '$labelText: use numbers only.';
    }
    if (v != null && v < 0) return '$labelText cannot be negative.';
    if (v != null && _decimals(text) > 2) return '$labelText: use at most 2 digits after the decimal point.';
  }
  return null;
}

Map<String, dynamic> rangeBody(List<String> texts) =>
    {'low': parseNumber(texts[0]), 'expected': parseNumber(texts[1]), 'high': parseNumber(texts[2])};

Map<String, dynamic> costBody(Map<String, String> costTexts) => {
      for (final (key, _) in costFields)
        if (parseNumber(costTexts[key] ?? '') != null) key: parseNumber(costTexts[key]!),
    };

/// Body for POST /crop-plans/{id}/items and PATCH /crop-plan-items/{id} (manual entry).
Map<String, dynamic> planItemBody({
  String? cropId,
  required String cropName,
  required double area,
  required DateTime sowing,
  required int durationDays,
  required List<String> yieldTexts,
  required List<String> priceTexts,
  required Map<String, String> costTexts,
  required String risk,
  required String basis,
}) =>
    {
      if (cropId != null) 'crop_id': cropId,
      'crop_name': cropName.trim(),
      'area_acres': double.parse(area.toStringAsFixed(3)),
      'sowing_date': isoDate(sowing),
      'duration_days': durationDays,
      'yield_per_acre_kg': rangeBody(yieldTexts),
      'price_per_kg': rangeBody(priceTexts),
      'cost': costBody(costTexts),
      'declared_risk': risk,
      'estimate_basis': basis,
    };

/// Body for POST /crop-plans/{id}/items/from-prediction: the prediction supplies yield, area, dates.
Map<String, dynamic> fromPredictionBody({
  required String predictionId,
  required List<String> priceTexts,
  required Map<String, String> costTexts,
  required String risk,
}) =>
    {
      'prediction_id': predictionId,
      'price_per_kg': rangeBody(priceTexts),
      'cost': costBody(costTexts),
      'declared_risk': risk,
    };

/// Checks the "new plan" form. Returns the first problem, or null.
String? validateNewPlan({required String name, required String landText, required double? farmArea, required String budgetText}) {
  if (name.trim().isEmpty) return 'Give the plan a name.';
  if (name.trim().length > 120) return 'The name is too long (120 characters at most).';
  final double? land;
  final double? budget;
  try {
    land = parseNumber(landText);
    budget = parseNumber(budgetText);
  } on FormatException {
    return 'Land and budget must be numbers.';
  }
  if (land == null || land <= 0) return 'Enter the land available in acres (more than 0).';
  if (farmArea != null && land > farmArea) return 'The land cannot be more than the farm (${number(farmArea)} acres).';
  if (budget != null && budget <= 0) return 'The budget must be more than 0, or left empty.';
  return null;
}
