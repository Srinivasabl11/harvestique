import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:harvestique/features/home/quotes/quote_hero.dart';
import 'package:harvestique/features/home/quotes/kannada_quotes.dart';
import 'package:harvestique/features/home/quotes/quote_rotation.dart';
import 'package:shared_preferences/shared_preferences.dart';

final _kannada = RegExp(r'[ಀ-೿]');

Future<int?> _stored() async => (await SharedPreferences.getInstance()).getInt(QuoteRotation.prefKey);

/// One app session: a fresh container, as after a kill and restart.
class _Session {
  _Session(this.tester)
      : container = ProviderContainer(
          // the test binding's clock follows fake time, including time spent in pumpAndSettle
          overrides: [quoteClockProvider.overrideWithValue(() => tester.binding.clock.now())],
        );

  final WidgetTester tester;
  final ProviderContainer container;

  KannadaQuote? get quote => container.read(quoteTickerProvider);
  int? get number => quote?.number;
  bool get timerActive => container.read(quoteTickerProvider.notifier).isTimerActive;

  Future<void> start() async {
    container.read(quoteTickerProvider);
    await tester.pump(); // let the stored number load
  }

  Future<void> elapse(Duration d) async {
    await tester.pump(d);
  }

  /// Must run before the test ends, or flutter_test reports a pending timer.
  void dispose() => container.dispose();
}

void _lifecycle(WidgetTester tester, List<AppLifecycleState> states) {
  for (final s in states) {
    tester.binding.handleAppLifecycleStateChanged(s);
  }
}

const _toBackground = [AppLifecycleState.inactive, AppLifecycleState.hidden, AppLifecycleState.paused];
const _toForeground = [AppLifecycleState.hidden, AppLifecycleState.inactive, AppLifecycleState.resumed];
const _sec = Duration(seconds: 1);
const _ms = Duration(milliseconds: 1);

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('quote data', () {
    test('has all 100 quotes, numbered 1..100 in order, no duplicates, all Kannada', () {
      expect(kannadaQuotes, hasLength(100));
      expect([for (final q in kannadaQuotes) q.number], List.generate(100, (i) => i + 1));
      expect(kannadaQuotes.map((q) => q.kannada).toSet(), hasLength(100));
      for (final q in kannadaQuotes) {
        expect(q.kannada, contains(_kannada), reason: 'quote ${q.number}');
        expect(q.kannada.trim(), q.kannada);
      }
    });

    test('keeps the exact wording of the first and last quotes', () {
      expect(kannadaQuotes.first.kannada, 'ರೈತನ ಕೈಯಲ್ಲಿ ಮಣ್ಣು ಮಾತ್ರವಲ್ಲ, ಒಂದು ಕುಟುಂಬದ ಭವಿಷ್ಯ ಇರುತ್ತದೆ.');
      expect(kannadaQuotes.last.kannada, 'ಮಣ್ಣಿನ ಮೇಲೆ ಬಿದ್ದ ಅವನ ಬೆವರಿನ ಹನಿಗಳು, ನಮ್ಮ ಬದುಕಿನ ಮೇಲೆ ಬಿದ್ದ ಆಶೀರ್ವಾದಗಳು.');
    });

    test('an out-of-range stored value restarts at quote 1', () async {
      SharedPreferences.setMockInitialValues({QuoteRotation.prefKey: 250});
      expect((await QuoteRotation().advance()).number, 1);
    });
  });

  group('20-second rotation', () {
    testWidgets('fresh install shows 1; advances exactly every 20 s and stores each step', (tester) async {
      final s = _Session(tester);
      await s.start();
      expect(s.number, 1);
      expect(await _stored(), 1);

      await s.elapse(const Duration(seconds: 20) - _ms);
      expect(s.number, 1);
      await s.elapse(_ms);
      expect(s.number, 2);
      expect(await _stored(), 2);

      await s.elapse(const Duration(seconds: 20) - _ms);
      expect(s.number, 2);
      await s.elapse(_ms);
      expect(s.number, 3);
      expect(await _stored(), 3);
      s.dispose();
    });

    testWidgets('runs 1 → 100 in order and wraps to 1', (tester) async {
      final s = _Session(tester);
      await s.start();
      final seen = <int>[s.number!];
      for (var i = 0; i < 100; i++) {
        await s.elapse(QuoteTicker.interval);
        seen.add(s.number!);
      }
      expect(seen, [...List.generate(100, (i) => i + 1), 1]);
      s.dispose();
    });

    testWidgets('quote 100 is followed by quote 1', (tester) async {
      SharedPreferences.setMockInitialValues({QuoteRotation.prefKey: 99});
      final s = _Session(tester);
      await s.start();
      expect(s.number, 100);
      await s.elapse(QuoteTicker.interval);
      expect(s.number, 1);
      s.dispose();
    });

    testWidgets('a restart continues with the quote after the last one shown', (tester) async {
      final first = _Session(tester);
      await first.start();
      await first.elapse(QuoteTicker.interval); // 1 -> 2
      expect(first.number, 2);
      first.dispose(); // app killed

      final second = _Session(tester);
      await second.start();
      expect(second.number, 3);
      second.dispose();
    });

    testWidgets('reading the quote again in the same session neither advances nor restarts the timer', (tester) async {
      final s = _Session(tester);
      await s.start();
      await s.elapse(const Duration(seconds: 15));
      s.container.read(quoteTickerProvider);
      s.container.read(quoteTickerProvider);
      expect(s.number, 1);
      await s.elapse(const Duration(seconds: 5));
      expect(s.number, 2); // still on the original schedule
      s.dispose();
    });
  });

  group('background and resume', () {
    testWidgets('pauses in the background and continues with the time that was left', (tester) async {
      final s = _Session(tester);
      await s.start();
      await s.elapse(const Duration(seconds: 8));

      _lifecycle(tester, _toBackground);
      expect(s.timerActive, isFalse);
      await s.elapse(const Duration(minutes: 5));
      expect(s.number, 1, reason: 'background time does not count');
      expect(await _stored(), 1);

      _lifecycle(tester, _toForeground);
      expect(s.timerActive, isTrue);
      await s.elapse(const Duration(seconds: 12) - _ms);
      expect(s.number, 1);
      await s.elapse(_ms);
      expect(s.number, 2);
      // the next quote gets a full 20 s again
      await s.elapse(QuoteTicker.interval - _ms);
      expect(s.number, 2);
      await s.elapse(_ms);
      expect(s.number, 3);
      s.dispose();
    });

    testWidgets('repeated resume events never create a second timer', (tester) async {
      final s = _Session(tester);
      await s.start();
      _lifecycle(tester, _toBackground);
      _lifecycle(tester, _toForeground);
      _lifecycle(tester, [AppLifecycleState.resumed, AppLifecycleState.resumed]);
      _lifecycle(tester, _toBackground);
      _lifecycle(tester, _toForeground);

      // With a duplicate timer the quote would move twice per interval.
      for (var expected = 2; expected <= 5; expected++) {
        await s.elapse(QuoteTicker.interval);
        expect(s.number, expected);
      }
      s.dispose();
    });

    testWidgets('going to the background exactly as a quote changes does not lose or double a step', (tester) async {
      final s = _Session(tester);
      await s.start();
      await s.elapse(QuoteTicker.interval - _sec);
      _lifecycle(tester, _toBackground);
      await s.elapse(const Duration(minutes: 1));
      _lifecycle(tester, _toForeground);
      await s.elapse(_sec);
      expect(s.number, 2);
      await s.elapse(QuoteTicker.interval);
      expect(s.number, 3);
      s.dispose();
    });
  });

  group('timer cleanup', () {
    testWidgets('disposing the session cancels the timer and stops listening to lifecycle', (tester) async {
      final s = _Session(tester);
      await s.start();
      expect(s.timerActive, isTrue);
      final notifier = s.container.read(quoteTickerProvider.notifier);
      s.dispose();
      expect(notifier.isTimerActive, isFalse);
      _lifecycle(tester, _toBackground);
      _lifecycle(tester, _toForeground);
      expect(notifier.isTimerActive, isFalse, reason: 'no timer comes back after disposal');
      await tester.pump(const Duration(minutes: 1));
      expect(await _stored(), 1);
    });
  });

  group('hero widget', () {
    Widget host(ProviderContainer container, Widget page, {double textScale = 1}) => UncontrolledProviderScope(
          container: container,
          child: MaterialApp(
            home: MediaQuery(
              data: MediaQueryData(size: const Size(320, 900), textScaler: TextScaler.linear(textScale)),
              child: Scaffold(body: page),
            ),
          ),
        );

    // Stand-ins for Farmer Home and Buyer Market: both place the hero at the top of a list.
    Widget farmerHome() =>
        ListView(key: const ValueKey('farmer'), children: const [HarvestiqueQuoteHero(), Text('Namaskara')]);
    Widget buyerMarket() =>
        ListView(key: const ValueKey('buyer'), children: const [HarvestiqueQuoteHero(), Text('Search future harvests')]);

    String text(int n) => kannadaQuotes[n - 1].kannada;

    testWidgets('both screens show the same quote at the same time and change together', (tester) async {
      final s = _Session(tester);
      await tester.pumpWidget(
        host(s.container, Column(children: [Expanded(child: farmerHome()), Expanded(child: buyerMarket())])),
      );
      await tester.pumpAndSettle();
      expect(find.text(text(1)), findsNWidgets(2));
      expect(find.text('1 / 100'), findsNWidgets(2));

      await s.elapse(QuoteTicker.interval);
      await tester.pumpAndSettle();
      expect(find.text(text(1)), findsNothing);
      expect(find.text(text(2)), findsNWidgets(2));
      expect(find.text('2 / 100'), findsNWidgets(2));
      await tester.pumpWidget(const SizedBox());
      s.dispose();
    });

    testWidgets('switching between the screens neither resets nor double-advances the quote', (tester) async {
      final s = _Session(tester);
      await tester.pumpWidget(host(s.container, farmerHome()));
      await tester.pump(); // quote 1 loaded; its 20 s start now
      await s.elapse(const Duration(seconds: 10));

      await tester.pumpWidget(host(s.container, buyerMarket()));
      await s.elapse(const Duration(seconds: 5));
      await tester.pumpWidget(host(s.container, farmerHome()));
      await s.elapse(const Duration(seconds: 5) - _ms);
      expect(s.number, 1);
      await s.elapse(_ms);
      await tester.pumpAndSettle();
      expect(find.text(text(2)), findsOneWidget);

      await tester.pumpWidget(host(s.container, buyerMarket()));
      await s.elapse(QuoteTicker.interval);
      await tester.pumpAndSettle();
      expect(find.text(text(3)), findsOneWidget);
      expect(await _stored(), 3);
      await tester.pumpWidget(const SizedBox());
      s.dispose();
    });

    testWidgets('branding stays put while only the quote fades', (tester) async {
      final s = _Session(tester);
      await tester.pumpWidget(host(s.container, farmerHome()));
      await tester.pumpAndSettle();
      final image = tester.element(find.byType(Image));
      final wordmark = tester.element(find.text('HARVESTIQUE'));

      await s.elapse(QuoteTicker.interval);
      await tester.pump(const Duration(milliseconds: 300)); // mid-fade: old and new quote both present
      expect(find.text(text(1)), findsOneWidget);
      expect(find.text(text(2)), findsOneWidget);
      expect(find.byType(FadeTransition), findsWidgets);
      expect(tester.element(find.byType(Image)), same(image), reason: 'flag image is not rebuilt as a new element');
      expect(tester.element(find.text('HARVESTIQUE')), same(wordmark));

      await tester.pumpAndSettle();
      expect(find.text(text(1)), findsNothing);
      await tester.pumpWidget(const SizedBox());
      s.dispose();
    });

    testWidgets('the longest quote fits a small phone with large text, including mid-fade', (tester) async {
      final longest = kannadaQuotes.reduce((a, b) => a.kannada.length >= b.kannada.length ? a : b);
      SharedPreferences.setMockInitialValues({QuoteRotation.prefKey: longest.number - 2});
      final s = _Session(tester);
      await tester.pumpWidget(host(s.container, farmerHome(), textScale: 1.6));
      await tester.pumpAndSettle();
      await s.elapse(QuoteTicker.interval); // fade into the longest quote
      await tester.pump(const Duration(milliseconds: 300));
      expect(tester.takeException(), isNull);
      await tester.pumpAndSettle();
      expect(find.text(longest.kannada), findsOneWidget);
      expect(tester.takeException(), isNull); // no RenderFlex overflow
      await tester.pumpWidget(const SizedBox());
      s.dispose();
    });
  });
}
