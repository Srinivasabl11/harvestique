import 'dart:async';

import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'kannada_quotes.dart';

/// Deterministic quote sequence: 1, 2, ... 100, then 1 again.
/// Stores the number last shown, so a killed and reopened app continues from the next one.
class QuoteRotation {
  QuoteRotation({List<KannadaQuote> quotes = kannadaQuotes}) : _quotes = quotes;

  static const prefKey = 'home_quote_last_shown';

  final List<KannadaQuote> _quotes;

  /// Moves to the next quote and remembers it.
  Future<KannadaQuote> advance() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final last = prefs.getInt(prefKey); // null on a fresh install
      final valid = last != null && last >= 1 && last <= _quotes.length;
      final next = valid ? last % _quotes.length + 1 : 1;
      await prefs.setInt(prefKey, next);
      return _quotes[next - 1];
    } catch (_) {
      return _quotes.first; // storage unavailable: still show a quote, never a random one
    }
  }
}

/// Wall clock for the quote timer; tests replace it to control elapsed time.
final quoteClockProvider = Provider<DateTime Function()>((ref) => DateTime.now);

/// The one app-wide quote source. Farmer Home and Buyer Market both watch it, so they always show
/// the same quote, driven by a single timer.
///
/// - Starts once per app session (a ProviderScope): advances one step from the stored quote, so a fresh
///   install starts at 1 and every launch continues with the next one.
/// - Every [interval] of foreground time it advances one step and stores the new number.
/// - Background policy: while the app is not in the foreground the timer is stopped; on return it
///   continues with the time that was left for the current quote. Time in the background never counts.
/// - Kept alive for the whole session, so tab switches, rebuilds and sign-out/sign-in never reset it.
final quoteTickerProvider = NotifierProvider<QuoteTicker, KannadaQuote?>(QuoteTicker.new);

class QuoteTicker extends Notifier<KannadaQuote?> with WidgetsBindingObserver {
  static const interval = Duration(seconds: 20);

  final _rotation = QuoteRotation();
  Timer? _timer;
  DateTime? _runningSince; // start of the current foreground stretch for this quote
  Duration _remaining = interval;
  bool _foreground = true;
  bool _advancing = false;
  bool _disposed = false;

  /// Whether a timer is currently scheduled (for tests).
  @visibleForTesting
  bool get isTimerActive => _timer?.isActive ?? false;

  @override
  KannadaQuote? build() {
    final binding = WidgetsBinding.instance;
    binding.addObserver(this);
    final lifecycle = binding.lifecycleState;
    _foreground = lifecycle == null || lifecycle == AppLifecycleState.resumed;
    ref.onDispose(() {
      _disposed = true;
      _timer?.cancel();
      _timer = null;
      binding.removeObserver(this);
    });
    _step();
    return null;
  }

  DateTime _now() => ref.read(quoteClockProvider)();

  Future<void> _step() async {
    if (_advancing) return;
    _advancing = true;
    _stop();
    final next = await _rotation.advance();
    _advancing = false;
    if (_disposed) return;
    state = next;
    _remaining = interval;
    if (_foreground) _start();
  }

  void _start() {
    _timer?.cancel(); // never more than one timer
    _runningSince = _now();
    _timer = Timer(_remaining, _step);
  }

  void _stop() {
    _timer?.cancel();
    _timer = null;
    final since = _runningSince;
    if (since != null) {
      final left = _remaining - _now().difference(since);
      _remaining = left.isNegative ? Duration.zero : left;
      _runningSince = null;
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    final foreground = state == AppLifecycleState.resumed;
    if (foreground == _foreground) return; // repeated or intermediate states change nothing
    _foreground = foreground;
    if (_advancing) return; // _step starts the timer itself once the new quote is stored
    if (foreground) {
      _start();
    } else {
      _stop();
    }
  }
}
