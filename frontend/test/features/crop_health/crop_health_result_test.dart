import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:harvestique/features/crop_health/crop_health_screen.dart';

Widget _wrap(Map<String, dynamic> r) => MaterialApp(home: Scaffold(body: SingleChildScrollView(child: CropHealthResult(r: r))));

/// The old model categories must never reach the farmer.
final _oldLabels = RegExp(r'\b(unknown|possible disease|possible deficiency|stress|most likely)\b', caseSensitive: false);

Map<String, dynamic> _decision(String status, {String? title, String summary = 'Summary.', String? confidence, List<String> signs = const [], List<String> steps = const ['Step one.']}) => {
      'status': status,
      'reason': 'r',
      'title': title ??
          {'healthy': 'Healthy', 'needs_attention': 'Needs attention', 'retake_photo': 'Clearer photo needed', 'unavailable': 'Photo check unavailable'}[status],
      'summary': summary,
      'confidence': confidence,
      'confidence_text': confidence == null ? null : 'Confidence: $confidence. The AI can be wrong.',
      'signs': signs,
      'next_steps': steps,
      'is_diagnosis': false,
    };

Map<String, dynamic> _analysis(Map<String, dynamic> decision, {Object? score = 7}) => {
      'decision': decision,
      'condition': {'score': score, 'out_of': 10, 'text': 'Moderate visible damage', 'method': 'Visual condition score: starts at 10.'},
      'sections': [
        {'id': 'photo', 'title': 'Photo check', 'items': ['The photo shows a plant close up.']},
        {'id': 'observations', 'title': 'What is visible', 'items': ['Brown spots, several']},
        {'id': 'limitations', 'title': 'Limits of this check', 'items': <String>[]},
        {'id': 'next', 'title': 'What to do next', 'items': decision['next_steps']},
      ],
    };

/// A result as the server sends it: the decision at the top level and inside the stored report. The internal
/// category and its numbers are still in the payload (for evaluations) and must not be displayed.
Map<String, dynamic> _result(Map<String, dynamic> decision, {Object? score = 7}) => {
      'status': decision['status'],
      'decision': decision,
      'label': 'possible_disease',
      'probabilities': {'healthy': 0.1, 'possible_disease': 0.65, 'stress': 0.05, 'possible_deficiency': 0.05, 'unknown': 0.15},
      'features': {'symptoms': ['brown_spots'], 'analysis': _analysis(decision, score: score)},
      'quality_flags': <String>[],
      'explanation': 'Brown patches can be a sign of disease.',
      'advice': 'Confirm with an agriculture officer.',
      'disclaimer': 'Advisory. Not a diagnosis.',
      'model_name': 'ollama-vision',
      'model_version': 'gemma3:4b',
    };

String _allText(WidgetTester tester) =>
    tester.widgetList<Text>(find.byType(Text)).map((t) => t.data ?? t.textSpan?.toPlainText() ?? '').join(' | ');

void main() {
  testWidgets('needs attention shows the signs, the confidence and the next steps, never the old categories', (tester) async {
    await tester.pumpWidget(_wrap(_result(_decision('needs_attention',
        summary: 'Visible signs that may point to a problem: brown spots (several).',
        confidence: 'medium',
        signs: ['brown spots (several)'],
        steps: ['Count how many plants show these signs.', 'Show the plant to an agriculture officer.'],),),),);
    expect(find.text('Needs attention'), findsOneWidget);
    expect(find.textContaining('Visible signs that may point'), findsOneWidget);
    expect(find.text('Confidence: medium. The AI can be wrong.'), findsOneWidget);
    expect(find.text('• brown spots (several)'), findsOneWidget);
    expect(find.text('What is visible'), findsNothing); // the signs above already say it
    expect(find.text('What to do next'), findsOneWidget);
    expect(find.text('• Show the plant to an agriculture officer.'), findsOneWidget);
    expect(find.text('7/10  Moderate visible damage'), findsOneWidget);
    expect(find.byType(LinearProgressIndicator), findsNothing); // no category bars
    expect(find.text('Advisory. Not a diagnosis.'), findsOneWidget);
    expect(_oldLabels.hasMatch(_allText(tester)), isFalse, reason: _allText(tester));
  });

  testWidgets('healthy is shown with its confidence and the score', (tester) async {
    await tester.pumpWidget(_wrap(_result(_decision('healthy', summary: 'No spots, yellowing, holes, drying or other damage is visible.', confidence: 'high'), score: 10)));
    expect(find.text('Healthy'), findsOneWidget);
    expect(find.text('Confidence: high. The AI can be wrong.'), findsOneWidget);
    expect(find.text('10/10  Moderate visible damage'), findsOneWidget);
    expect(find.text('What is visible'), findsOneWidget);
    expect(_oldLabels.hasMatch(_allText(tester)), isFalse);
  });

  for (final status in ['retake_photo', 'unavailable']) {
    testWidgets('$status makes no health claim and shows no score', (tester) async {
      await tester.pumpWidget(_wrap(_result(_decision(status, summary: 'No health result is given.', steps: ['Take a sharp close-up.']), score: null)));
      expect(find.text(status == 'retake_photo' ? 'Clearer photo needed' : 'Photo check unavailable'), findsOneWidget);
      expect(find.text('Healthy'), findsNothing);
      expect(find.text('Needs attention'), findsNothing);
      expect(find.textContaining('/10'), findsNothing);
      expect(find.textContaining('Confidence'), findsNothing);
      expect(find.text('• Take a sharp close-up.'), findsOneWidget);
      expect(_oldLabels.hasMatch(_allText(tester)), isFalse);
    });
  }

  testWidgets('Kannada text from the server is shown as given', (tester) async {
    await tester.pumpWidget(_wrap(_result(_decision('healthy', title: 'ಆರೋಗ್ಯಕರ', summary: 'ಈ ಫೋಟೋದಲ್ಲಿ ಹಾನಿ ಕಾಣುತ್ತಿಲ್ಲ.', confidence: 'medium'))));
    expect(find.text('ಆರೋಗ್ಯಕರ'), findsOneWidget);
    expect(find.text('ಈ ಫೋಟೋದಲ್ಲಿ ಹಾನಿ ಕಾಣುತ್ತಿಲ್ಲ.'), findsOneWidget);
  });

  testWidgets('a decision nested only in the stored report is used too', (tester) async {
    final r = _result(_decision('needs_attention', signs: ['yellowing'], confidence: 'low'))..remove('decision');
    await tester.pumpWidget(_wrap(r));
    expect(find.text('Needs attention'), findsOneWidget);
  });

  testWidgets('an old cached result without a decision shows no category at all', (tester) async {
    final r = _result(_decision('healthy'))
      ..remove('decision')
      ..['features'] = {'symptoms': ['brown_spots']};
    await tester.pumpWidget(_wrap(r));
    expect(find.textContaining('Refresh to see this result'), findsOneWidget);
    expect(_oldLabels.hasMatch(_allText(tester)), isFalse);
  });

  test('history titles come from the decision', () {
    expect(cropHealthTitle(_result(_decision('needs_attention'))), 'Needs attention');
    expect(cropHealthTitle({'label': 'possible_disease', 'features': <String, dynamic>{}}), 'Photo check');
  });
}
