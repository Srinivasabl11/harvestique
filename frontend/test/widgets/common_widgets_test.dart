import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:harvestique/core/errors/app_failure.dart';
import 'package:harvestique/core/network/api_client.dart';
import 'package:harvestique/core/widgets/common.dart';

Widget wrap(Widget child) => MaterialApp(home: Scaffold(body: child));

void main() {
  testWidgets('data kind chips say where a number comes from', (tester) async {
    await tester.pumpWidget(
        wrap(const Column(children: [DataKindChip('measured'), DataKindChip('estimate'), DataKindChip('simulated')])),);
    expect(find.text('Measured'), findsOneWidget);
    expect(find.text('Estimate'), findsOneWidget);
    expect(find.text('Simulated'), findsOneWidget);
  });

  testWidgets('confidence badge never presents a heuristic as measured accuracy', (tester) async {
    await tester.pumpWidget(wrap(const ConfidenceBadge(score: 62, level: 'medium', basis: 'heuristic')));
    expect(find.text('Confidence 62/100 · Medium'), findsOneWidget);
    expect(find.text('Rule-based estimate, not a measured accuracy.'), findsOneWidget);
  });

  testWidgets('risk chip shows missing data honestly', (tester) async {
    await tester.pumpWidget(wrap(const RiskChip(level: 'insufficient_data')));
    expect(find.text('Risk: not enough data'), findsOneWidget);
  });

  testWidgets('loaded view: loading, error with retry, empty, offline', (tester) async {
    var retried = false;
    Widget view(AsyncSnapshot<Loaded<List<int>>> snap) => wrap(
          LoadedView<List<int>>(
            future: snap,
            onRetry: () => retried = true,
            isEmpty: (d) => d.isEmpty,
            emptyMessage: 'Nothing yet',
            builder: (context, d) => Text('items: ${d.length}'),
          ),
        );

    await tester.pumpWidget(view(const AsyncSnapshot.waiting()));
    expect(find.byType(CircularProgressIndicator), findsOneWidget);

    await tester.pumpWidget(view(const AsyncSnapshot.withError(ConnectionState.done, AppFailure('network', 'Cannot reach'))));
    expect(find.text('Cannot reach'), findsOneWidget);
    await tester.tap(find.text('Try again'));
    expect(retried, isTrue);

    await tester.pumpWidget(view(const AsyncSnapshot.withData(ConnectionState.done, Loaded(<int>[]))));
    expect(find.text('Nothing yet'), findsOneWidget);

    await tester
        .pumpWidget(view(AsyncSnapshot.withData(ConnectionState.done, Loaded(const [1, 2], cachedAt: DateTime(2026, 10, 8, 9)))));
    expect(find.text('items: 2'), findsOneWidget);
    expect(find.textContaining('Offline: showing data saved on'), findsOneWidget);
  });
}
