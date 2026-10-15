import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:harvestique/features/crop_health/crop_health_screen.dart';

Widget _wrap(Map<String, dynamic> r) => MaterialApp(home: Scaffold(body: SingleChildScrollView(child: CropHealthResult(r: r))));

Map<String, dynamic> _result({required String label, required Map<String, dynamic> features, List<String> flags = const []}) => {
      'label': label,
      'probabilities': {'healthy': 0.1, 'possible_disease': 0.65, 'stress': 0.05, 'possible_deficiency': 0.05, 'unknown': 0.15},
      'features': features,
      'quality_flags': flags,
      'explanation': 'Brown spots on green leaves.\nWhat the AI sees (may be wrong): Round brown spots.',
      'advice': 'Confirm with an agriculture officer.',
      'disclaimer': 'Advisory. Not a diagnosis.',
      'model_name': 'ollama-vision',
      'model_version': 'gemma3:4b',
    };

void main() {
  testWidgets('a vision result shows the likely category, the signs noticed and the disclaimer', (tester) async {
    await tester.pumpWidget(_wrap(_result(label: 'possible_disease', features: {'symptoms': ['brown_spots', 'dry_edges']})));
    expect(find.textContaining('Most likely'), findsOneWidget);
    expect(find.textContaining('Signs the AI noticed'), findsOneWidget);
    expect(find.byType(LinearProgressIndicator), findsNWidgets(5));
    expect(find.text('Advisory. Not a diagnosis.'), findsOneWidget);
  });

  testWidgets('a colour-only result shows no health label and no probability bars', (tester) async {
    await tester.pumpWidget(_wrap(_result(label: 'unknown', features: {'mode': 'measurements_only', 'green': 0.9})));
    expect(find.text('Colour check (no health label)'), findsOneWidget);
    expect(find.textContaining('Most likely'), findsNothing);
    expect(find.byType(LinearProgressIndicator), findsNothing);
  });

  test('the title says how sure the result is', () {
    Map<String, dynamic> r(String label, Map<String, dynamic> f) => {'label': label, 'features': f};
    expect(cropHealthTitle(r('possible_disease', {'ai_confidence': 'medium'})), 'Most likely: Possible disease');
    expect(cropHealthTitle(r('possible_disease', {'ai_confidence': 'low'})), 'Uncertain: Possible disease');
    expect(cropHealthTitle(r('unknown', {'ai_confidence': 'low'})), 'Unclear from this photo');
    expect(cropHealthTitle(r('unknown', {'mode': 'measurements_only'})), 'Colour check (no health label)');
  });

  test('bars use whole percentages that add up to exactly 100', () {
    // a "high" answer stored with 3 decimals rounded bar by bar to 65 + 21 + 5 + 5 + 5 = 101 %
    final p = wholePercents({'possible_disease': 0.65, 'unknown': 0.21, 'healthy': 0.047, 'stress': 0.047, 'possible_deficiency': 0.046});
    expect(p.values.reduce((a, b) => a + b), 100);
    expect(p['possible_disease'], 65);
    expect(wholePercents({'a': 1, 'b': 1, 'c': 1}).values.reduce((a, b) => a + b), 100);
    expect(wholePercents({'a': 0, 'b': 0}).values.every((v) => v == 0), isTrue);
  });

  Map<String, dynamic> analysis({required Object? score, required String text, String? reason}) => {
        'condition': {'score': score, 'out_of': 10, 'text': text, 'method': 'Visual condition score: starts at 10.', 'withheld_reason': reason},
        'sections': [
          {'id': 'photo', 'title': 'Photo check', 'items': ['The photo shows a plant close up.']},
          {'id': 'observations', 'title': 'What is visible', 'items': ['Brown spots, several']},
          {'id': 'explanations', 'title': 'Possible explanations (not a diagnosis)', 'items': ['Spots are often an infection.']},
          {'id': 'limitations', 'title': 'Limits of this check', 'items': <String>[]},
          {'id': 'next', 'title': 'What to do next', 'items': ['Look at nearby plants.']},
        ],
      };

  testWidgets('a structured report shows the condition score and each section in order', (tester) async {
    await tester.pumpWidget(_wrap(_result(
      label: 'possible_disease',
      features: {'symptoms': ['brown_spots'], 'ai_confidence': 'medium', 'analysis': analysis(score: 7, text: 'Moderate visible damage')},
    ),),);
    expect(find.text('7/10  Moderate visible damage'), findsOneWidget);
    expect(find.text('Visual condition score: starts at 10.'), findsOneWidget);
    expect(find.text('What is visible'), findsOneWidget);
    expect(find.text('• Brown spots, several'), findsOneWidget);
    expect(find.text('Possible explanations (not a diagnosis)'), findsOneWidget);
    expect(find.text('Limits of this check'), findsNothing); // an empty section is not shown
    expect(find.textContaining('Signs the AI noticed'), findsNothing); // replaced by "What is visible"
    expect(find.textContaining('not a measured probability'), findsOneWidget);
    expect(find.byType(LinearProgressIndicator), findsNWidgets(5));
    expect(find.text('Advisory. Not a diagnosis.'), findsOneWidget);
  });

  testWidgets('no score is shown as a number when the evidence is insufficient', (tester) async {
    await tester.pumpWidget(_wrap(_result(
      label: 'unknown',
      features: {'analysis': analysis(score: null, text: 'No score: the photo is not clear.', reason: 'photo')},
      flags: ['blurry'],
    ),),);
    expect(find.text('No score: the photo is not clear.'), findsOneWidget);
    expect(find.textContaining('/10'), findsNothing);
    expect(find.text('Visual condition score: starts at 10.'), findsNothing);
  });

  testWidgets('Kannada report text from the server is shown as given', (tester) async {
    await tester.pumpWidget(_wrap(_result(
      label: 'healthy',
      features: {'ai_confidence': 'high', 'analysis': analysis(score: 10, text: 'ಈ ಫೋಟೋದಲ್ಲಿ ಕಾಣುವ ಹಾನಿ ಇಲ್ಲ')},
    ),),);
    expect(find.text('10/10  ಈ ಫೋಟೋದಲ್ಲಿ ಕಾಣುವ ಹಾನಿ ಇಲ್ಲ'), findsOneWidget);
  });
}
