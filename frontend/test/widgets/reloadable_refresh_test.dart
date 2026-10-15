import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:harvestique/core/widgets/common.dart';

void main() {
  testWidgets('pull to refresh shows the newly loaded data', (tester) async {
    var n = 0;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Reloadable<int>(
            load: () async => live(Future.value(++n)),
            builder: (context, v, reload) => ListView(children: [Text('value $v')]),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('value 1'), findsOneWidget);
    await tester.fling(find.byType(ListView), const Offset(0, 400), 1000);
    await tester.pumpAndSettle();
    expect(n, 2);
    expect(find.text('value 2'), findsOneWidget);
  });

  testWidgets('reload from a button shows the newly loaded data', (tester) async {
    var n = 0;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Reloadable<int>(
            load: () async => live(Future.value(++n)),
            builder: (context, v, reload) => ListView(children: [Text('value $v'), TextButton(onPressed: reload, child: const Text('again'))]),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('again'));
    await tester.pumpAndSettle();
    expect(n, 2);
    expect(find.text('value 2'), findsOneWidget);
  });
}
