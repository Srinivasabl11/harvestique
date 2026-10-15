import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:harvestique/core/errors/app_failure.dart';
import 'package:harvestique/core/network/api_client.dart';
import 'package:harvestique/core/storage/offline_cache.dart';
import 'package:harvestique/core/storage/token_store.dart';
import 'package:harvestique/core/widgets/record_actions.dart';
import 'package:harvestique/features/farm/edit_dialogs.dart';

class _NoTokens extends TokenStore {
  @override
  Future<String?> access() async => null;

  @override
  Future<String?> refresh() async => null;
}

class _FakeApi extends ApiClient {
  _FakeApi() : super(tokens: _NoTokens(), cache: OfflineCache());

  final calls = <(String, String, Object?)>[];

  @override
  Future<Map<String, dynamic>> patch(String path, Map<String, dynamic> body) async {
    calls.add(('PATCH', path, body));
    return {};
  }

  @override
  Future<Map<String, dynamic>> post(String path, {Object? body, String? idempotencyKey}) async {
    calls.add(('POST', path, body));
    return {};
  }
}

/// A button that runs [deleteOrFallback] and shows the result.
class _Host extends StatefulWidget {
  const _Host({required this.delete, required this.fallback});

  final Future<void> Function() delete;
  final Future<void> Function() fallback;

  @override
  State<_Host> createState() => _HostState();
}

class _HostState extends State<_Host> {
  String result = 'none';

  @override
  Widget build(BuildContext context) => Scaffold(
        body: Column(
          children: [
            Text('result: $result'),
            FilledButton(
              onPressed: () async {
                final r = await deleteOrFallback(
                  context,
                  what: 'this farm',
                  delete: widget.delete,
                  historyCodes: {'farm_not_empty'},
                  fallbackLabel: 'Archive farm',
                  fallback: widget.fallback,
                );
                setState(() => result = r.name);
              },
              child: const Text('remove'),
            ),
          ],
        ),
      );
}

Widget _dialogApp(ApiClient api, Widget dialog) => ProviderScope(
      overrides: [apiProvider.overrideWithValue(api), tokenStoreProvider.overrideWithValue(_NoTokens())],
      child: MaterialApp(
        home: Builder(
          builder: (context) => Scaffold(
            body: FilledButton(
                onPressed: () => showDialog<bool>(context: context, builder: (_) => dialog), child: const Text('open'),),
          ),
        ),
      ),
    );

void main() {
  test('coordinates: both or neither, in range', () {
    expect(validateCoordinates('', ''), isNull);
    expect(validateCoordinates('12.29', '76.63'), isNull);
    expect(validateCoordinates('12.29', ''), contains('both'));
    expect(validateCoordinates('120', '76'), contains('-90 and 90'));
    expect(validateCoordinates('12', '200'), contains('-180 and 180'));
    expect(validateCoordinates('abc', '76'), contains('numbers'));
  });

  testWidgets('delete asks first and deletes', (tester) async {
    var deleted = 0;
    await tester.pumpWidget(MaterialApp(home: _Host(delete: () async => deleted++, fallback: () async {})));
    await tester.tap(find.text('remove'));
    await tester.pumpAndSettle();
    expect(find.text('Delete this farm?'), findsOneWidget);
    await tester.tap(find.text('Keep'));
    await tester.pumpAndSettle();
    expect(deleted, 0);
    expect(find.text('result: cancelled'), findsOneWidget);
    await tester.tap(find.text('remove'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Delete'));
    await tester.pumpAndSettle();
    expect(deleted, 1);
    expect(find.text('result: deleted'), findsOneWidget);
  });

  testWidgets('a record with history is archived instead, never deleted', (tester) async {
    var archived = 0;
    await tester.pumpWidget(
      MaterialApp(
        home: _Host(
          delete: () async =>
              throw const AppFailure('farm_not_empty', 'This farm still has plots, expenses, activities or crop plans.'),
          fallback: () async => archived++,
        ),
      ),
    );
    await tester.tap(find.text('remove'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Delete'));
    await tester.pumpAndSettle();
    expect(find.text('Keep the history'), findsOneWidget);
    expect(find.textContaining('This farm still has plots'), findsOneWidget);
    await tester.tap(find.text('Archive farm'));
    await tester.pumpAndSettle();
    expect(archived, 1);
    expect(find.text('result: fallback'), findsOneWidget);
  });

  testWidgets('editing a farm sends the changed fields and checks coordinates', (tester) async {
    final api = _FakeApi();
    final farm = {'id': 'f1', 'name': 'Green Acres', 'total_area_acres': 10, 'latitude': null, 'longitude': null};
    await tester.pumpWidget(_dialogApp(api, EditFarmDialog(farm: farm)));
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
    await tester.enterText(find.widgetWithText(TextField, 'Latitude (optional)'), '12.2958');
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();
    expect(find.text('Enter both latitude and longitude, or leave both empty.'), findsOneWidget);
    expect(api.calls, isEmpty);
    await tester.enterText(find.widgetWithText(TextField, 'Longitude (optional)'), '76.6394');
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();
    expect(api.calls.single.$2, '/farms/f1');
    final body = api.calls.single.$3! as Map<String, dynamic>;
    expect(body['latitude'], 12.2958);
    expect(body['longitude'], 76.6394);
    expect(body['name'], 'Green Acres');
  });

  testWidgets('an observation loss must be a percentage', (tester) async {
    final api = _FakeApi();
    await tester.pumpWidget(_dialogApp(api, const ObservationDialog(cycleId: 'c1')));
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
    await tester.enterText(find.widgetWithText(TextField, 'Estimated loss % (optional)'), '150');
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();
    expect(find.text('Loss must be a percentage from 0 to 100.'), findsOneWidget);
    await tester.enterText(find.widgetWithText(TextField, 'Estimated loss % (optional)'), '20');
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();
    expect(api.calls.single.$2, '/crop-cycles/c1/observations');
    expect((api.calls.single.$3! as Map)['estimated_loss_percent'], 20);
  });
}
