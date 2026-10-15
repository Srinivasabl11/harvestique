import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:harvestique/features/buyer/search_screen.dart';
import 'package:harvestique/features/harvest/grading_screen.dart';

Map<String, dynamic> _criteria() => {
      'profile': 'fresh',
      'rule': 'The grade is the lowest level of any check.',
      'note': 'Not an official AGMARK grade.',
      'grades': {'A': 'Grade A: best.', 'B': 'Grade B: standard.', 'C': 'Grade C: lower.'},
      'attributes': [
        for (final id in ['size', 'damage'])
          {
            'id': id,
            'title': id == 'size' ? 'Size and uniformity' : 'Damage',
            'photo_visible': true,
            'levels': [
              {'level': 0, 'text': '$id best'},
              {'level': 1, 'text': '$id middle'},
              {'level': 2, 'text': '$id worst'},
            ],
          },
      ],
    };

Map<String, dynamic> _data({Map<String, dynamic>? proposal, Map<String, int>? levels, String? grade, bool locked = false}) => {
      'crop_name': 'Tomato',
      'harvested_kg': 800,
      'status': grade != null ? 'graded' : (proposal != null ? 'needs_review' : 'not_graded'),
      'status_text': 'Status text.',
      'criteria': _criteria(),
      'proposal': proposal,
      'levels': levels,
      'criteria_grade': grade,
      'grade': grade,
      'grade_text': grade == null ? null : 'Grade $grade: text.',
      'grade_source': grade == null ? null : 'manual',
      'locked': locked,
      'warnings': locked ? ['Locked: the hub check applies.'] : <String>[],
    };

class _Calls {
  final confirms = <(Map<String, int>, String?, String?)>[];
}

Future<_Calls> _pump(WidgetTester tester, Map<String, dynamic> data) async {
  final calls = _Calls();
  // a tall phone, so the whole form is built (ListView builds only what is on screen)
  tester.view.physicalSize = const Size(1080, 4800);
  tester.view.devicePixelRatio = 2;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(MaterialApp(
    home: Scaffold(
      body: GradingForm(
        data: data,
        onPhoto: (_) {},
        onConfirm: (levels, grade, reason) => calls.confirms.add((levels, grade, reason)),
      ),
    ),
  ),);
  return calls;
}

Finder _confirmButton() => find.byWidgetPredicate((w) => w is FilledButton);

void main() {
  test('the grade is the worst level, and there is none while a check is open', () {
    expect(gradeFor(['size', 'damage'], {'size': 0, 'damage': 0}), 'A');
    expect(gradeFor(['size', 'damage'], {'size': 0, 'damage': 1}), 'B');
    expect(gradeFor(['size', 'damage'], {'size': 2, 'damage': 1}), 'C');
    expect(gradeFor(['size', 'damage'], {'size': 0}), isNull);
  });

  testWidgets('manual grading: no grade until every check is rated, then confirm sends the ratings', (tester) async {
    final calls = await _pump(tester, _data());
    expect(find.textContaining('No grade yet'), findsOneWidget);
    expect(tester.widget<FilledButton>(_confirmButton()).onPressed, isNull);

    await tester.tap(find.text('size best'));
    await tester.pump();
    expect(find.textContaining('No grade yet. Still open: Damage'), findsOneWidget);
    await tester.tap(find.text('damage middle'));
    await tester.pump();
    expect(find.textContaining('Your ratings give grade B'), findsOneWidget);

    await tester.ensureVisible(_confirmButton());
    await tester.tap(_confirmButton());
    expect(calls.confirms.single.$1, {'size': 0, 'damage': 1});
    expect(calls.confirms.single.$2, isNull);
  });

  testWidgets('an AI proposal is pre-filled, marked as a suggestion and never shown as final', (tester) async {
    await _pump(
      tester,
      _data(proposal: {
        'status': 'proposed',
        'message': 'Review each one.',
        'levels': {'size': 0, 'damage': 2},
        'proposed_grade': 'C',
        'description': 'Some cracked tomatoes.',
      },),
    );
    expect(find.text('AI suggestion (check it)'), findsOneWidget);
    expect(find.text('Suggested grade: C (not final)'), findsOneWidget);
    expect(find.text('AI suggestion'), findsNWidgets(2));
    expect(find.textContaining('Your ratings give grade C'), findsOneWidget);
    expect(find.textContaining('What the AI saw (may be wrong)'), findsOneWidget);
  });

  testWidgets('a lower grade needs a reason; a higher one is not offered', (tester) async {
    final calls = await _pump(tester, _data(levels: {'size': 0, 'damage': 1}, grade: 'B'));
    expect(find.text('Grade B: text.'), findsOneWidget);
    await tester.ensureVisible(find.byType(DropdownButton<String?>));
    await tester.tap(find.byType(DropdownButton<String?>));
    await tester.pumpAndSettle();
    expect(find.text('A'), findsNothing); // above what the ratings support
    await tester.tap(find.text('C').last);
    await tester.pumpAndSettle();
    expect(tester.widget<FilledButton>(_confirmButton()).onPressed, isNull); // reason missing
    await tester.enterText(find.byType(TextField), 'Rain damage after sorting');
    await tester.pump();
    await tester.ensureVisible(_confirmButton());
    await tester.tap(_confirmButton());
    expect(calls.confirms.single.$2, 'C');
    expect(calls.confirms.single.$3, 'Rain damage after sorting');
  });

  testWidgets('a locked grade is read-only', (tester) async {
    await _pump(tester, _data(levels: {'size': 0, 'damage': 0}, grade: 'A', locked: true));
    expect(find.text('Locked: the hub check applies.'), findsOneWidget);
    expect(_confirmButton(), findsNothing);
    expect(find.text('Camera'), findsNothing);
  });

  test('buyers see whether a grade was given after harvest or is only expected', () {
    expect(gradeLine({'grade': 'A', 'grade_basis': 'farmer_graded'}), 'Grade A · graded by the farmer after harvest');
    expect(gradeLine({'grade': 'B', 'grade_basis': 'farmer_expected'}), contains('not graded yet'));
  });
}
