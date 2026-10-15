import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:harvestique/features/crop_health/crop_health_screen.dart';

Widget _wrap(Map<String, dynamic> r) => MaterialApp(home: Scaffold(body: SingleChildScrollView(child: CropHealthResult(r: r))));

/// The old model categories and the long report must never reach the farmer.
final _old = RegExp(r'\b(unknown|possible disease|possible deficiency|stress|most likely|probabilit)', caseSensitive: false);

Map<String, dynamic> _decision({
  String status = 'healthy',
  Map<String, dynamic>? item,
  num? score,
  String? category,
  String categoryText = 'Very good',
  String? confidence = 'high',
  String summary = 'No spots, yellowing, holes, drying or other damage is visible in this photo.',
  List<String> steps = const ['Keep checking every few days.', 'Check a few more plants.'],
}) =>
    {
      'status': status,
      'reason': 'r',
      'title': 'Healthy',
      'summary': summary,
      'item': item,
      'health_score': score,
      'health_category': category,
      'category_text': categoryText,
      'score_meaning': 'Health score: how healthy it looks in this photo. It is not a diagnosis.',
      'confidence': confidence,
      'confidence_label': confidence,
      'confidence_text': 'Confidence: long sentence that is not shown.',
      'signs': <String>[],
      'next_steps': steps,
      'is_diagnosis': false,
    };

Map<String, dynamic> _result(Map<String, dynamic> d) => {
      'status': d['status'],
      'decision': d,
      'label': 'possible_disease',
      'probabilities': {'possible_disease': 0.65},
      'features': {
        'analysis': {
          'decision': d,
          'sections': [
            {'id': 'limitations', 'title': 'Limits of this check', 'items': ['A long generic limitation.']},
          ],
        },
      },
      'disclaimer': 'A long disclaimer paragraph.',
      'model_name': 'ollama-vision',
      'model_version': 'gemma4:31b',
    };

const _ragi = {'name': 'Ragi', 'local_name': 'ರಾಗಿ', 'display_name': 'Ragi', 'parent': 'cereals_grains', 'parent_name': 'Cereals and grains', 'source': 'photo'};

String _allText(WidgetTester tester) =>
    tester.widgetList<Text>(find.byType(Text)).map((t) => t.data ?? t.textSpan?.toPlainText() ?? '').join(' | ');

void main() {
  testWidgets('shows only the essentials: item, parent category, category, score, confidence', (tester) async {
    await tester.pumpWidget(_wrap(_result(_decision(item: _ragi, score: 100, category: 'A'))));
    expect(find.text('Ragi'), findsOneWidget);
    expect(find.text('Cereals and grains'), findsOneWidget);
    expect(find.text('Identified from the photo (AI estimate)'), findsOneWidget);
    expect(find.text('A'), findsOneWidget);
    expect(find.text('Category A · Very good'), findsOneWidget);
    expect(find.text('Health score 100%'), findsOneWidget);
    expect(find.text('AI confidence: high'), findsOneWidget);
    expect(find.text('Next: Keep checking every few days.'), findsOneWidget);
    expect(find.text('Next: Check a few more plants.'), findsNothing); // one next step only
    final text = _allText(tester);
    expect(text, isNot(contains('A long generic limitation.'))); // no report sections
    expect(text, isNot(contains('A long disclaimer paragraph.')));
    expect(text, isNot(contains('long sentence that is not shown')));
    expect(_old.hasMatch(text), isFalse, reason: text);
  });

  testWidgets('B and C show their score with one decimal when needed', (tester) async {
    await tester.pumpWidget(_wrap(_result(_decision(
      status: 'needs_attention',
      item: _ragi,
      score: 45.5,
      category: 'B',
      categoryText: 'Good',
      confidence: 'low',
      summary: 'Visible signs that may point to a problem: brown spots (many).',
    ),),),);
    expect(find.text('Category B · Good'), findsOneWidget);
    expect(find.text('Health score 45.5%'), findsOneWidget);
    expect(find.text('AI confidence: low'), findsOneWidget);
  });

  testWidgets('without enough evidence it says Unable to classify, with no score', (tester) async {
    await tester.pumpWidget(_wrap(_result(_decision(
      status: 'retake_photo',
      categoryText: 'Unable to classify',
      confidence: null,
      summary: 'The item in the photo could not be identified with confidence, so no health result is given.',
      steps: const ['Photograph one kind of crop or produce at a time, close up, in daylight.'],
    ),),),);
    expect(find.text('Unable to classify'), findsOneWidget);
    expect(find.text('?'), findsOneWidget);
    expect(find.textContaining('Health score'), findsNothing);
    expect(find.textContaining('AI confidence'), findsNothing);
    expect(find.textContaining('could not be identified'), findsOneWidget);
    expect(find.textContaining('Next: Photograph one kind'), findsOneWidget);
  });

  testWidgets('Kannada results are shown as the server sends them', (tester) async {
    await tester.pumpWidget(_wrap(_result(_decision(
      item: {..._ragi, 'display_name': 'ರಾಗಿ', 'parent_name': 'ಧಾನ್ಯಗಳು'},
      score: 90,
      category: 'A',
      categoryText: 'ತುಂಬಾ ಉತ್ತಮ',
      confidence: 'ಹೆಚ್ಚು',
      summary: 'ಈ ಫೋಟೋದಲ್ಲಿ ಹಾನಿ ಕಾಣುತ್ತಿಲ್ಲ.',
    ),),),);
    expect(find.text('ರಾಗಿ'), findsOneWidget);
    expect(find.text('ಧಾನ್ಯಗಳು'), findsOneWidget);
    expect(find.text('Category A · ತುಂಬಾ ಉತ್ತಮ'), findsOneWidget);
    expect(find.text('AI confidence: ಹೆಚ್ಚು'), findsOneWidget);
  });

  testWidgets('a crop chosen by the farmer is not labelled as an AI identification', (tester) async {
    await tester.pumpWidget(_wrap(_result(_decision(item: {..._ragi, 'source': 'your_crop'}, score: 100, category: 'A'))));
    expect(find.text('Ragi'), findsOneWidget);
    expect(find.textContaining('Identified from the photo'), findsNothing);
  });

  testWidgets('an old cached result without a decision asks to refresh', (tester) async {
    await tester.pumpWidget(_wrap({'label': 'healthy', 'features': <String, dynamic>{}}));
    expect(find.text('Refresh to see this result.'), findsOneWidget);
  });

  test('history titles show the category and score, else the result title', () {
    expect(cropHealthTitle(_result(_decision(item: _ragi, score: 87.4, category: 'A'))), 'Category A · 87%');
    expect(cropHealthTitle(_result(_decision(status: 'retake_photo'))), 'Healthy');
    expect(cropHealthTitle({'label': 'healthy', 'features': <String, dynamic>{}}), 'Photo check');
  });

  test('category colours differ per band', () {
    const scheme = ColorScheme.light();
    final colours = {for (final c in ['A', 'B', 'C', null]) categoryColor(c, scheme)};
    expect(colours.length, 4);
  });
}
