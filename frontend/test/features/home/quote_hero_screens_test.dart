import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:harvestique/core/errors/app_failure.dart';
import 'package:harvestique/core/network/api_client.dart';
import 'package:harvestique/core/storage/offline_cache.dart';
import 'package:harvestique/core/storage/token_store.dart';
import 'package:harvestique/features/buyer/buyer_home_screen.dart';
import 'package:harvestique/features/home/farmer_home_screen.dart';
import 'package:harvestique/features/home/quotes/karnataka_quote_hero.dart';
import 'package:harvestique/features/home/quotes/kannada_quotes.dart';
import 'package:harvestique/features/home/quotes/quote_rotation.dart';
import 'package:harvestique/features/home/weather_card.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _NoTokens extends TokenStore {
  @override
  Future<String?> access() async => null;

  @override
  Future<String?> refresh() async => null;
}

enum _Server { ok, unreachable, slow }

/// Backend stand-in for the real Farmer Home and Buyer Market screens.
class _FakeApi extends ApiClient {
  _FakeApi(this.server) : super(tokens: _NoTokens(), cache: OfflineCache());

  final _Server server;
  final _never = Completer<Never>();

  Future<T> _answer<T>(T value) => switch (server) {
        _Server.ok => Future.value(value),
        _Server.unreachable => Future.error(const AppFailure('network', 'Cannot reach the Harvestique server.')),
        _Server.slow => _never.future,
      };

  @override
  Future<List<Map<String, dynamic>>> getPage(String path, {Map<String, dynamic>? query}) => _answer([]);

  @override
  Future<List<Map<String, dynamic>>> getList(String path, {Map<String, dynamic>? query}) => _answer([]);

  @override
  Future<Map<String, dynamic>> getObj(String path, {Map<String, dynamic>? query}) => _answer({});
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  final quote1 = kannadaQuotes[0].kannada;
  final quote2 = kannadaQuotes[1].kannada;

  Future<ProviderContainer> pumpScreen(WidgetTester tester, Widget screen, _Server server) async {
    final container = ProviderContainer(
      overrides: [
        apiProvider.overrideWithValue(_FakeApi(server)),
        quoteClockProvider.overrideWithValue(() => tester.binding.clock.now()),
      ],
    );
    tester.view.physicalSize = const Size(1080, 2400);
    tester.view.devicePixelRatio = 2.75;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      UncontrolledProviderScope(container: container, child: MaterialApp(home: Scaffold(body: screen))),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 700)); // quote fade-in
    return container;
  }

  Future<void> finish(WidgetTester tester, ProviderContainer container) async {
    await tester.pumpWidget(const SizedBox());
    container.dispose(); // cancels the quote timer
  }

  void expectHero({required String quote, required String counter}) {
    expect(find.byType(KarnatakaQuoteHero), findsOneWidget);
    expect(find.text('HARVESTIQUE'), findsOneWidget);
    expect(
      find.byWidgetPredicate((w) => w is Image && w.image == const AssetImage(KarnatakaQuoteHero.asset)),
      findsOneWidget,
    );
    expect(find.text(quote), findsOneWidget);
    expect(find.text(counter), findsOneWidget);
  }

  void expectAbove(WidgetTester t, Finder top, Finder below) {
    expect(
      t.getBottomLeft(top).dy <= t.getTopLeft(below).dy,
      isTrue,
      reason: 'hero must sit above the existing content',
    );
  }

  group('Farmer Home (real screen)', () {
    testWidgets('shows the hero above the greeting and weather once data loads', (t) async {
      final c = await pumpScreen(t, const FarmerHomeScreen(), _Server.ok);
      expectHero(quote: quote1, counter: '1 / 100');
      expect(find.textContaining('Namaskara'), findsOneWidget);
      expect(find.byType(FarmWeatherCard), findsOneWidget);
      expectAbove(t, find.byType(KarnatakaQuoteHero), find.byType(FarmWeatherCard));
      expectAbove(t, find.byType(KarnatakaQuoteHero), find.textContaining('Namaskara'));
      await finish(t, c);
    });

    testWidgets('still shows the hero when the server is unreachable', (t) async {
      final c = await pumpScreen(t, const FarmerHomeScreen(), _Server.unreachable);
      expect(find.text('Try again'), findsOneWidget); // existing error panel is kept
      expectHero(quote: quote1, counter: '1 / 100');
      expectAbove(t, find.byType(KarnatakaQuoteHero), find.text('Try again'));
      await finish(t, c);
    });

    testWidgets('shows the hero while the server is still loading', (t) async {
      final c = await pumpScreen(t, const FarmerHomeScreen(), _Server.slow);
      expect(find.bySemanticsLabel('Loading'), findsOneWidget);
      expectHero(quote: quote1, counter: '1 / 100');
      await finish(t, c);
    });
  });

  group('Buyer Market (real screen)', () {
    testWidgets('shows the hero above the search button and supply list once data loads', (t) async {
      final c = await pumpScreen(t, const BuyerHomeScreen(), _Server.ok);
      expectHero(quote: quote1, counter: '1 / 100');
      expect(find.text('Search future harvests'), findsOneWidget);
      expect(find.text('No future supply is on offer right now.'), findsOneWidget);
      expectAbove(t, find.byType(KarnatakaQuoteHero), find.text('Search future harvests'));
      await finish(t, c);
    });

    testWidgets('still shows the hero when the server is unreachable', (t) async {
      final c = await pumpScreen(t, const BuyerHomeScreen(), _Server.unreachable);
      expect(find.text('Try again'), findsOneWidget);
      expectHero(quote: quote1, counter: '1 / 100');
      await finish(t, c);
    });

    testWidgets('shows the hero while the server is still loading', (t) async {
      final c = await pumpScreen(t, const BuyerHomeScreen(), _Server.slow);
      expect(find.bySemanticsLabel('Loading'), findsOneWidget);
      expectHero(quote: quote1, counter: '1 / 100');
      await finish(t, c);
    });
  });

  testWidgets('the real Farmer Home and Buyer Market show the same quote and advance together', (t) async {
    final container = ProviderContainer(
      overrides: [
        apiProvider.overrideWithValue(_FakeApi(_Server.ok)),
        quoteClockProvider.overrideWithValue(() => t.binding.clock.now()),
      ],
    );
    t.view.physicalSize = const Size(1080, 4800);
    t.view.devicePixelRatio = 2.75;
    addTearDown(t.view.reset);
    await t.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: const MaterialApp(
          home: Scaffold(
            body: Column(
              children: [Expanded(child: FarmerHomeScreen()), Expanded(child: BuyerHomeScreen())],
            ),
          ),
        ),
      ),
    );
    await t.pump();
    await t.pump(const Duration(milliseconds: 700));
    expect(find.byType(KarnatakaQuoteHero), findsNWidgets(2));
    expect(find.text(quote1), findsNWidgets(2));

    await t.pump(QuoteTicker.interval - const Duration(milliseconds: 700) - const Duration(milliseconds: 1));
    expect(find.text(quote2), findsNothing);
    await t.pump(const Duration(milliseconds: 1));
    await t.pump(const Duration(milliseconds: 700));
    expect(find.text(quote1), findsNothing);
    expect(find.text(quote2), findsNWidgets(2));
    expect(find.text('2 / 100'), findsNWidgets(2));
    await finish(t, container);
  });
}
