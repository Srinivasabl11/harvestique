import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:harvestique/core/errors/app_failure.dart';
import 'package:harvestique/core/network/api_client.dart';
import 'package:harvestique/core/storage/offline_cache.dart';
import 'package:harvestique/core/storage/token_store.dart';
import 'package:harvestique/features/home/weather_card.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _NoTokens extends TokenStore {
  @override
  Future<String?> access() async => null;

  @override
  Future<String?> refresh() async => null;
}

class _FakeApi extends ApiClient {
  _FakeApi(this.responses) : super(tokens: _NoTokens(), cache: OfflineCache());

  final Map<String, List<Object>> responses; // farm id -> queued answers (Map or AppFailure)
  final asked = <String>[];

  @override
  Future<Map<String, dynamic>> getObj(String path, {Map<String, dynamic>? query}) async {
    final id = path.split('/')[2];
    asked.add(id);
    final queue = responses[id]!;
    final next = queue.length > 1 ? queue.removeAt(0) : queue.first;
    if (next is AppFailure) throw next;
    return next as Map<String, dynamic>;
  }
}

Map<String, dynamic> _weather({bool raining = false}) => {
      'status': 'fresh',
      'fetched_at': '2026-10-10T09:30:00Z',
      'source': 'open_meteo',
      'note': 'Model estimates from Open-Meteo (free), not measurements on your farm.',
      'current': {
        'temperature_c': 29.4,
        'humidity_pct': 61,
        'condition': raining ? 'Light rain' : 'Partly cloudy',
        'raining_now': raining,
        'precipitation_mm': raining ? 0.4 : 0,
        'is_day': true,
      },
      'next_hours': [
        {'time': '2026-10-10T10:00:00+05:30', 'rain_probability_pct': 10},
        {'time': '2026-10-10T11:00:00+05:30', 'rain_probability_pct': 70},
        {'time': '2026-10-10T12:00:00+05:30', 'rain_probability_pct': null},
      ],
      'days': [
        {'day': '2026-10-11', 'tmin_c': 21, 'tmax_c': 32, 'rain_mm': 0, 'rain_probability_pct': 15, 'condition': 'Overcast'},
      ],
    };

Widget _app(ApiClient api, List<Map<String, dynamic>> farms) => ProviderScope(
      overrides: [apiProvider.overrideWithValue(api), tokenStoreProvider.overrideWithValue(_NoTokens())],
      child: MaterialApp(home: Scaffold(body: SingleChildScrollView(child: FarmWeatherCard(farms: farms)))),
    );

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('peak rain chance', () {
    expect(peakRainChance(const []), isNull);
    expect(peakRainChance(_weather()['next_hours'] as List<Map<String, dynamic>>)!.$1, 70);
  });

  testWidgets('shows temperature, rain now (model estimate) and the rain chance ahead', (tester) async {
    final api = _FakeApi({
      'f1': [_weather(raining: true)],
    });
    await tester.pumpWidget(_app(api, [
      {'id': 'f1', 'name': 'Green Acres', 'latitude': 12.3},
    ]),);
    await tester.pumpAndSettle();
    expect(find.text('29°C'), findsOneWidget);
    expect(find.text('Light rain'), findsOneWidget);
    expect(find.text('Raining now (model estimate)'), findsOneWidget);
    expect(find.textContaining('up to 70%'), findsOneWidget);
    expect(find.text('Estimate'), findsOneWidget);
    expect(find.textContaining('Overcast · 21–32°C · rain 15%'), findsOneWidget);
  });

  testWidgets('a farm without location explains what to do', (tester) async {
    final api = _FakeApi({
      'f1': [
        {
          'status': 'unavailable',
          'current': null,
          'next_hours': <dynamic>[],
          'days': <dynamic>[],
          'note': 'Add the farm location (latitude and longitude) to get weather: open the farm, then Edit farm.',
        },
      ],
    });
    await tester.pumpWidget(_app(api, [
      {'id': 'f1', 'name': 'No GPS'},
    ]),);
    await tester.pumpAndSettle();
    expect(find.textContaining('Edit farm'), findsOneWidget);
  });

  testWidgets('a failure offers Retry, and another farm can be chosen', (tester) async {
    final api = _FakeApi({
      'f1': [const AppFailure('network', 'Cannot reach the Harvestique server.'), _weather()],
      'f2': [_weather(raining: true)],
    });
    await tester.pumpWidget(_app(api, [
      {'id': 'f1', 'name': 'Green Acres', 'latitude': 12.3},
      {'id': 'f2', 'name': 'River Farm', 'latitude': 12.4},
    ]),);
    await tester.pumpAndSettle();
    expect(find.textContaining('Weather could not be loaded'), findsOneWidget);
    await tester.tap(find.text('Retry'));
    await tester.pumpAndSettle();
    expect(find.text('Partly cloudy'), findsOneWidget);
    await tester.tap(find.text('Green Acres'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('River Farm').last);
    await tester.pumpAndSettle();
    expect(api.asked.last, 'f2');
    expect(find.text('Light rain'), findsOneWidget);
  });
}
