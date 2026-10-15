import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:harvestique/core/errors/app_failure.dart';
import 'package:harvestique/core/network/api_client.dart';
import 'package:harvestique/core/storage/offline_cache.dart';
import 'package:harvestique/core/storage/token_store.dart';
import 'package:harvestique/features/farm/add_crop_screen.dart';

class _NoTokens extends TokenStore {
  @override
  Future<String?> access() async => null;

  @override
  Future<String?> refresh() async => null;
}

/// API double: returns a fixed crop catalog and records POSTs (optionally failing like the server).
class _FakeApi extends ApiClient {
  _FakeApi(this.crops, {this.failWith}) : super(tokens: _NoTokens(), cache: OfflineCache());

  final List<Map<String, dynamic>> crops;
  final AppFailure? failWith;
  final posts = <(String, Object?)>[];

  @override
  Future<List<Map<String, dynamic>>> getAll(String path, {Map<String, dynamic>? query, int maxItems = 1000}) =>
      getPage(path, query: query);

  @override
  Future<List<Map<String, dynamic>>> getPage(String path, {Map<String, dynamic>? query}) async => crops;

  @override
  Future<Map<String, dynamic>> post(String path, {Object? body, String? idempotencyKey}) async {
    posts.add((path, body));
    if (failWith != null) throw failWith!;
    return <String, dynamic>{'id': 'new-cycle'};
  }
}

const _tomato = <String, dynamic>{
  'id': 'crop-tomato',
  'name': 'Tomato',
  'local_name': 'ಟೊಮೆಟೊ',
  'category': 'vegetable',
  'typical_duration_days': 100,
};
const _ragi = <String, dynamic>{
  'id': 'crop-ragi',
  'name': 'Ragi',
  'local_name': 'ರಾಗಿ',
  'category': 'cereal',
  'typical_duration_days': 110,
};
const _plot = <String, dynamic>{'id': 'plot-1', 'name': 'Plot 1', 'area_acres': 2.0};

Widget _app(ApiClient api, {List<Map<String, dynamic>> cycles = const []}) {
  return ProviderScope(
    overrides: [apiProvider.overrideWithValue(api)],
    child: MaterialApp(home: _Host(cycles: cycles)),
  );
}

/// Opens the Add Crop screen and shows what it returned (as plain text, not a SnackBar).
class _Host extends StatefulWidget {
  const _Host({required this.cycles});

  final List<Map<String, dynamic>> cycles;

  @override
  State<_Host> createState() => _HostState();
}

class _HostState extends State<_Host> {
  String _result = 'none';

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Column(
        children: [
          Text('result: $_result'),
          FilledButton(
            onPressed: () async {
              final saved = await Navigator.of(context).push<bool>(
                MaterialPageRoute<bool>(builder: (_) => AddCropScreen(plot: _plot, plotCycles: widget.cycles)),
              );
              setState(() => _result = '$saved');
            },
            child: const Text('open'),
          ),
        ],
      ),
    );
  }
}

/// The Add Crop screen's ListView (the search field has its own inner Scrollable).
final _list = find.byType(Scrollable).first;

void main() {
  final today = DateTime(2026, 10, 9);

  group('validateCrop', () {
    String? v(
            {Map<String, dynamic>? crop = _tomato,
            String status = 'growing',
            DateTime? sowing,
            DateTime? expected,
            double? area = 1,}) =>
        validateCrop(
            crop: crop, status: status, sowing: sowing ?? today, expected: expected, area: area, plotArea: 2, today: today,);

    test('accepts a complete crop', () => expect(v(expected: DateTime(2027, 1, 17)), isNull));
    test('needs a crop', () => expect(v(crop: null), contains('Choose a crop')));
    test('needs a positive area', () => expect(v(area: 0), contains('area')));
    test('area cannot exceed the plot', () => expect(v(area: 2.5), contains('cannot be more than the plot')));
    test('growing crops cannot be sown in the future', () => expect(v(sowing: DateTime(2026, 10, 20)), contains('future')));
    test('planned crops may be sown in the future', () => expect(v(status: 'planned', sowing: DateTime(2026, 10, 20)), isNull));
    test('harvest must be after sowing', () => expect(v(expected: today), contains('after the sowing')));
  });

  test('cropBody matches the API contract (POST /plots/{id}/crop-cycles)', () {
    final body = cropBody(crop: _tomato, status: 'growing', sowing: today, expected: DateTime(2027, 1, 17), area: 1.23456);
    expect(body, {
      'crop_id': 'crop-tomato',
      'status': 'growing',
      'sowing_date': '2026-10-09',
      'area_acres': 1.235,
      'expected_harvest_date': '2027-01-17',
    });
    expect(
        cropBody(crop: _tomato, status: 'planned', sowing: today, expected: null, area: 1).containsKey('expected_harvest_date'),
        isFalse,);
  });

  test('freeArea subtracts planned and growing crops only', () {
    final cycles = [
      {'status': 'growing', 'area_acres': 1.25},
      {'status': 'planned', 'area_acres': 0.5},
      {'status': 'harvested', 'area_acres': 2.0},
    ];
    expect(freeArea(_plot, cycles), 0.25);
    expect(freeArea(_plot, const []), 2.0);
    expect(
        freeArea(_plot, [
          {'status': 'growing', 'area_acres': 3.0},
        ]),
        0,);
  });

  testWidgets('choosing a crop and saving posts it to the plot and returns true', (tester) async {
    final api = _FakeApi([_tomato, _ragi]);
    await tester.pumpWidget(_app(api));
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
    expect(find.text('Tomato'), findsOneWidget);
    expect(find.text('Ragi'), findsOneWidget);

    await tester.tap(find.text('Ragi'));
    await tester.pumpAndSettle();
    expect(find.text('Selected: Ragi'), findsOneWidget);

    await tester.scrollUntilVisible(find.text('Save crop'), 200, scrollable: _list);
    await tester.tap(find.text('Save crop'));
    await tester.pumpAndSettle();

    expect(api.posts, hasLength(1));
    final (path, body) = api.posts.single;
    expect(path, '/plots/plot-1/crop-cycles');
    final m = body! as Map<String, dynamic>;
    expect(m['crop_id'], 'crop-ragi');
    expect(m['status'], 'growing');
    expect(m['area_acres'], 2.0);
    expect(m['expected_harvest_date'], isNotNull); // filled from the crop's 110-day duration
    expect(find.text('result: true'), findsOneWidget); // screen closed and reported success to the farm page
  });

  testWidgets('saving without a crop shows the problem on the screen and sends nothing', (tester) async {
    final api = _FakeApi([_tomato]);
    await tester.pumpWidget(_app(api));
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('Save crop'), 200, scrollable: _list);
    await tester.tap(find.text('Save crop'));
    await tester.pumpAndSettle();
    expect(api.posts, isEmpty);
    await tester.scrollUntilVisible(find.text('Choose a crop from the list.'), -200, scrollable: _list);
    expect(find.text('Choose a crop from the list.'), findsOneWidget);
  });

  testWidgets('a server rejection is shown on the screen, which stays open', (tester) async {
    const failure = AppFailure('plot_capacity_exceeded',
        'Not enough free land: this crop cycle would put 4.000 acres in use at once on a 2.000-acre plot',);
    final api = _FakeApi([_tomato], failWith: failure);
    await tester.pumpWidget(_app(api, cycles: const [
      {'status': 'growing', 'area_acres': 2.0, 'crop_name': 'Beans'},
    ],),);
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.textContaining('Already on this plot: Beans'), 200, scrollable: _list);
    expect(find.textContaining('Already on this plot: Beans'), findsOneWidget);
    await tester.scrollUntilVisible(find.text('Tomato'), -200, scrollable: _list);
    await tester.ensureVisible(find.text('Tomato')); // fully on screen (the category chips sit above the list)
    await tester.pumpAndSettle();
    await tester.tap(find.text('Tomato'));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('Save crop'), 200, scrollable: _list);
    await tester.tap(find.text('Save crop'));
    await tester.pumpAndSettle();
    expect(api.posts, hasLength(1));
    await tester.scrollUntilVisible(find.textContaining('Not enough free land'), -200, scrollable: _list);
    expect(find.textContaining('Not enough free land'), findsOneWidget);
    expect(find.text('result: true'), findsNothing);
  });

  testWidgets('an empty crop catalog explains why nothing can be chosen', (tester) async {
    await tester.pumpWidget(_app(_FakeApi(const [])));
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
    expect(find.textContaining('crop list on the server is empty'), findsOneWidget);
  });
}
