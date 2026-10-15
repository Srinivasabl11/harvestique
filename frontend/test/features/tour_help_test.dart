import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:harvestique/core/network/api_client.dart';
import 'package:harvestique/core/storage/offline_cache.dart';
import 'package:harvestique/core/storage/token_store.dart';
import 'package:harvestique/features/help/help_screen.dart';
import 'package:harvestique/features/onboarding/tour.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _Tokens extends TokenStore {
  @override
  Future<String?> access() async => 'token';

  @override
  Future<String?> refresh() async => null;
}

class _FakeApi extends ApiClient {
  _FakeApi(this.user) : super(tokens: _Tokens(), cache: OfflineCache());

  Map<String, dynamic> user;
  final posts = <(String, Object?)>[];

  @override
  Future<Map<String, dynamic>> getObj(String path, {Map<String, dynamic>? query}) async => user;

  @override
  Future<Map<String, dynamic>> post(String path, {Object? body, String? idempotencyKey}) async {
    posts.add((path, body));
    if (path == '/auth/me/tour') user = {...user, 'tour_version_seen': (body! as Map)['version']};
    return user;
  }
}

Future<_FakeApi> _pump(WidgetTester tester, {required String role, required int seen, required Widget home}) async {
  SharedPreferences.setMockInitialValues({});
  final api = _FakeApi({'id': 'u-$role-$seen-${home.runtimeType}', 'role': role, 'full_name': 'Test', 'tour_version_seen': seen});
  await tester.pumpWidget(
    ProviderScope(
      overrides: [apiProvider.overrideWithValue(api), tokenStoreProvider.overrideWithValue(_Tokens())],
      child: MaterialApp(home: home),
    ),
  );
  await tester.pumpAndSettle(); // signed in via /auth/me
  return api;
}

void main() {
  testWidgets('a new farmer sees the tour once; Next/Back/Finish work and it is recorded', (tester) async {
    final api = await _pump(tester, role: 'farmer', seen: 0, home: const TourGate(child: Scaffold(body: Text('home'))));
    expect(find.text('Welcome to Harvestique'), findsOneWidget);
    expect(find.text('Guide 1 of ${farmerTour.length}'), findsOneWidget);
    expect(tester.widget<OutlinedButton>(find.widgetWithText(OutlinedButton, 'Back')).onPressed, isNull);
    await tester.tap(find.text('Next'));
    await tester.pumpAndSettle();
    expect(find.text('Your farm and plots'), findsOneWidget);
    await tester.tap(find.text('Back'));
    await tester.pumpAndSettle();
    expect(find.text('Welcome to Harvestique'), findsOneWidget);
    for (var i = 1; i < farmerTour.length; i++) {
      await tester.tap(find.text('Next'));
      await tester.pumpAndSettle();
    }
    expect(find.text('Ask Harvestique'), findsOneWidget);
    expect(find.text('Skip'), findsNothing);
    await tester.tap(find.text('Finish'));
    await tester.pumpAndSettle();
    expect(find.text('home'), findsOneWidget);
    expect(api.posts.single.$1, '/auth/me/tour');
    expect(api.posts.single.$2, {'version': kTourVersion});
  });

  testWidgets('skipping also counts as seen', (tester) async {
    final api = await _pump(tester, role: 'buyer', seen: 0, home: const TourGate(child: Scaffold(body: Text('home'))));
    expect(find.text('Welcome to Harvestique'), findsOneWidget);
    await tester.tap(find.text('Skip'));
    await tester.pumpAndSettle();
    expect(find.text('home'), findsOneWidget);
    expect(api.posts.single.$2, {'version': kTourVersion});
  });

  testWidgets('an account that has seen this version does not get the tour', (tester) async {
    // TourGate remembers it ran in this process; a fresh gate here still must not open for a seen account
    final api =
        await _pump(tester, role: 'farmer', seen: kTourVersion, home: const TourGate(child: Scaffold(body: Text('home'))));
    expect(find.text('Welcome to Harvestique'), findsNothing);
    expect(api.posts, isEmpty);
  });

  testWidgets('Help & guide: role-specific manual, search, and restarting the tour', (tester) async {
    await _pump(tester, role: 'farmer', seen: kTourVersion, home: const HelpScreen());
    expect(find.text('Farms and plots'), findsOneWidget);
    expect(find.text('Market and search'), findsNothing); // buyer-only section
    await tester.enterText(find.byType(TextField), 'expense');
    await tester.pumpAndSettle();
    expect(find.text('Expenses'), findsOneWidget);
    expect(find.text('Weather'), findsNothing);
    await tester.enterText(find.byType(TextField), 'zzzz');
    await tester.pumpAndSettle();
    expect(find.text('Nothing matches. Try another word.'), findsOneWidget);
    await tester.tap(find.text('Start the guided tour'));
    await tester.pumpAndSettle();
    expect(find.text('Welcome to Harvestique'), findsOneWidget);
  });

  test('every tour step and manual section has text', () {
    for (final s in [...farmerTour, ...buyerTour]) {
      expect(s.title.isNotEmpty && s.body.length > 20, isTrue);
    }
    for (final m in [...farmerManual, ...buyerManual]) {
      expect(m.points, isNotEmpty);
    }
  });
}
