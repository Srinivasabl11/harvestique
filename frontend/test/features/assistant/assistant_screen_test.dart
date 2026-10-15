import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:harvestique/core/errors/app_failure.dart';
import 'package:harvestique/core/network/api_client.dart';
import 'package:harvestique/core/storage/offline_cache.dart';
import 'package:harvestique/core/storage/token_store.dart';
import 'package:harvestique/features/assistant/assistant_screen.dart';
import 'package:harvestique/features/assistant/voice_engine.dart';
import 'package:harvestique/features/shell/shell_navigation.dart';

class _NoTokens extends TokenStore {
  @override
  Future<String?> access() async => null;

  @override
  Future<String?> refresh() async => null;
}

/// The phone's speech engines, scripted: the test "says" words and decides how speaking ends.
class FakeVoice implements VoiceEngine {
  bool initOk = true;
  bool voiceInstalled = true;
  bool holdSpeech = false;
  bool knRecognizer = true;
  List<String> nextAlternates = const [];
  void Function(List<String>)? onAlternates;
  late void Function(VoiceProblem) onError;
  late void Function() onDone;
  void Function(String, bool)? onResult;
  String _partial = '';
  int listens = 0;
  final longForms = <bool>[];
  final locales = <String>[];
  final spoken = <String>[];
  int stopSpeakingCalls = 0;
  Completer<bool>? speaking;

  bool get listening => onResult != null;

  void say(String words) {
    final r = onResult!;
    onResult = null;
    onAlternates?.call(nextAlternates);
    r(words, true);
  }

  void fail(VoiceProblem p) {
    onResult = null;
    onError(p);
  }

  /// Words recognised so far in the current segment (not final yet).
  void partial(String words) {
    _partial = words;
    onResult!(words, false);
  }

  /// Android ends a segment after a pause: the segment's text becomes final and the recogniser stops.
  void endSegment() {
    final r = onResult!;
    onResult = null;
    onAlternates?.call(nextAlternates);
    r(_partial, true);
    _partial = '';
    onDone();
  }

  @override
  bool get isListening => onResult != null;

  @override
  Future<bool> init({required void Function(VoiceProblem problem) onError, required void Function() onDone}) async {
    this.onError = onError;
    this.onDone = onDone;
    return initOk;
  }

  @override
  Future<void> listen({
    required String localeId,
    required void Function(String, bool) onResult,
    bool offlineOnly = false,
    bool longForm = false,
    void Function(List<String> alternates)? onAlternates,
  }) async {
    listens += 1;
    longForms.add(longForm);
    locales.add(localeId);
    this.onResult = onResult;
    this.onAlternates = onAlternates;
  }

  @override
  Future<bool> hasRecognizer(String language) async => language != 'kn' || knRecognizer;

  /// Stopping delivers what was heard as the final result, then "done" (like the Android recogniser).
  @override
  Future<void> stopListening() async {
    if (onResult != null) endSegment();
  }

  @override
  Future<void> cancelListening() async => onResult = null;

  @override
  Future<bool> speak(String text, String language) async {
    spoken.add(text);
    if (!voiceInstalled) return false;
    if (holdSpeech) {
      speaking = Completer<bool>();
      return speaking!.future;
    }
    return true;
  }

  @override
  Future<void> stopSpeaking() async {
    stopSpeakingCalls += 1;
    if (speaking != null && !speaking!.isCompleted) speaking!.complete(true);
  }

  @override
  Future<bool> hasVoice(String language) async => voiceInstalled;

  @override
  String? get ttsEngine => null;
}

class _FakeApi extends ApiClient {
  _FakeApi() : super(tokens: _NoTokens(), cache: OfflineCache());

  final posts = <(String, Map<String, dynamic>)>[];
  final replies = <Object>[]; // Map, AppFailure or Completer<Map<String, dynamic>>

  @override
  Future<Map<String, dynamic>> ask(String path, Map<String, dynamic> body) => post(path, body: body);

  @override
  Future<Map<String, dynamic>> post(String path, {Object? body, String? idempotencyKey}) async {
    posts.add((path, body! as Map<String, dynamic>));
    final next = replies.removeAt(0);
    if (next is AppFailure) throw next;
    if (next is Completer<Map<String, dynamic>>) return next.future;
    return next as Map<String, dynamic>;
  }
}

Map<String, dynamic> _answer(String text, {String intent = 'weather', Map<String, dynamic>? propose}) => {
      'language': 'en',
      'intent': intent,
      'answer': text,
      'requires_confirmation': propose != null,
      'proposed_action': propose,
      'tool_calls': <dynamic>[],
      'sources': <dynamic>[],
      'disclaimer': 'Advisory only.',
      'answer_kind': 'records',
    };

Future<(FakeVoice, _FakeApi)> _pump(WidgetTester tester, {FakeVoice? voice}) async {
  final v = voice ?? FakeVoice();
  final api = _FakeApi();
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        voiceEngineProvider.overrideWithValue(v),
        apiProvider.overrideWithValue(api),
        tokenStoreProvider.overrideWithValue(_NoTokens()),
      ],
      child: const MaterialApp(home: AssistantScreen()),
    ),
  );
  await tester.pumpAndSettle();
  return (v, api);
}

/// Press and hold the microphone (past the 200 ms hold delay). Release with `gesture.up()`.
Future<TestGesture> _hold(WidgetTester tester) async {
  final g = await tester.startGesture(tester.getCenter(find.byType(FloatingActionButton)));
  await tester.pump(const Duration(milliseconds: 300));
  await tester.pump();
  return g;
}

Future<void> _release(WidgetTester tester, TestGesture g) async {
  await g.up();
  await tester.pumpAndSettle();
}

Future<void> _tapMic(WidgetTester tester) async {
  await tester.tap(find.byType(FloatingActionButton));
  await tester.pumpAndSettle();
}

Future<void> _handsFree(WidgetTester tester) async {
  await tester.tap(find.byTooltip('Voice settings'));
  await tester.pumpAndSettle();
  await tester.tap(find.text('Conversation mode (listen again after each answer)'));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('typed questions work and carry the conversation for follow-ups', (tester) async {
    final (_, api) = await _pump(tester);
    api.replies
      ..add(_answer('Weather for Green Acres: 4 mm of rain.'))
      ..add(_answer('Tomorrow: 2 mm.'));
    await tester.enterText(find.byType(TextField), 'what is the weather');
    await tester.tap(find.byTooltip('Send'));
    await tester.pumpAndSettle();
    expect(find.text('Weather for Green Acres: 4 mm of rain.'), findsOneWidget);
    expect(api.posts.first.$1, '/assistant/chat');
    expect(api.posts.first.$2['history'], isEmpty);

    await tester.enterText(find.byType(TextField), 'and tomorrow?');
    await tester.tap(find.byTooltip('Send'));
    await tester.pumpAndSettle();
    expect(api.posts.last.$2['history'], [
      {'role': 'user', 'text': 'what is the weather'},
      {'role': 'assistant', 'text': 'Weather for Green Acres: 4 mm of rain.', 'intent': 'weather'},
    ]);
  });

  testWidgets('speaking a question: listen, ask by voice, speak the answer', (tester) async {
    final (voice, api) = await _pump(tester);
    api.replies.add(_answer('Rain expected.'));
    final g = await _hold(tester);
    expect(voice.listening, isTrue);
    expect(voice.locales.single, 'en_IN');
    expect(voice.longForms.single, isTrue);
    expect(find.textContaining('Recording 0:00'), findsOneWidget);
    voice.partial('will it rain tomorrow');
    await tester.pump();
    expect(find.text('will it rain tomorrow'), findsWidgets); // live transcript
    await _release(tester, g);
    expect(api.posts.single.$1, '/voice/intent');
    expect(api.posts.single.$2['transcript'], 'will it rain tomorrow');
    expect(voice.spoken, ['Rain expected.']);
    expect(voice.listening, isFalse); // not in conversation mode: does not listen again
  });

  testWidgets('Kannada listens with the Kannada recogniser', (tester) async {
    final (voice, _) = await _pump(tester);
    await tester.tap(find.text('ಕನ್ನಡ'));
    await tester.pumpAndSettle();
    final g = await _hold(tester);
    expect(voice.locales.single, 'kn_IN');
    await _release(tester, g);
    expect(find.textContaining('ನನಗೆ ಏನೂ ಕೇಳಿಸಲಿಲ್ಲ'), findsOneWidget); // nothing said: asked to hold while speaking
  });

  testWidgets('conversation mode listens again after each answer and stops after silence', (tester) async {
    final (voice, api) = await _pump(tester);
    api.replies.add(_answer('Rain expected.'));
    await _handsFree(tester);
    await _tapMic(tester);
    voice.say('weather');
    await tester.pumpAndSettle();
    expect(voice.spoken, ['Rain expected.']);
    expect(voice.listening, isTrue); // listening again, hands-free
    voice.fail(VoiceProblem.silence);
    await tester.pumpAndSettle();
    expect(voice.listening, isTrue); // one silence: tries once more
    voice.fail(VoiceProblem.silence);
    await tester.pumpAndSettle();
    expect(voice.listening, isFalse);
    expect(find.textContaining("I didn't hear anything"), findsOneWidget);
    expect(find.text('Conversation mode'), findsNothing);
  });

  testWidgets('"stop" ends conversation mode without asking the server', (tester) async {
    final (voice, api) = await _pump(tester);
    await _handsFree(tester);
    await _tapMic(tester);
    voice.say('stop');
    await tester.pumpAndSettle();
    expect(api.posts, isEmpty);
    expect(find.text('Okay, conversation mode is off.'), findsOneWidget);
  });

  testWidgets('the microphone interrupts a spoken answer', (tester) async {
    final voice = FakeVoice()..holdSpeech = true;
    final (_, api) = await _pump(tester, voice: voice);
    api.replies.add(_answer('A long answer that is still being read out.'));
    await tester.enterText(find.byType(TextField), 'weather');
    await tester.tap(find.byTooltip('Send'));
    await tester.pump();
    await tester.pump();
    expect(find.text('Speaking… tap to interrupt'), findsOneWidget);
    await _tapMic(tester); // a short tap stops the answer
    expect(voice.stopSpeakingCalls, greaterThan(0));
    expect(voice.listening, isFalse);
    expect(find.text('Hold the microphone while you speak'), findsOneWidget);
  });

  testWidgets('a refused microphone permission explains itself and typing still works', (tester) async {
    final (voice, api) = await _pump(tester);
    final g = await _hold(tester);
    voice.fail(VoiceProblem.permission);
    await tester.pumpAndSettle();
    await _release(tester, g);
    expect(find.textContaining('Microphone permission is off'), findsOneWidget);
    expect(api.posts, isEmpty);
    expect(tester.widget<FloatingActionButton>(find.byType(FloatingActionButton)).onPressed, isNull);
    api.replies.add(_answer('Typed answer.'));
    await tester.enterText(find.byType(TextField), 'weather');
    await tester.tap(find.byTooltip('Send'));
    await tester.pumpAndSettle();
    expect(find.text('Typed answer.'), findsOneWidget);
  });

  testWidgets('no speech recogniser: the screen says so and offers typing', (tester) async {
    await _pump(tester, voice: FakeVoice()..initOk = false);
    expect(find.textContaining('Speech recognition is not available'), findsOneWidget);
    expect(find.text('Type your question'), findsOneWidget);
  });

  testWidgets('a proposed expense is saved only after a spoken "yes"', (tester) async {
    final (voice, api) = await _pump(tester);
    final action = {
      'tool': 'record_expense',
      'args': {'farm_id': 'f1', 'category': 'fertilizer', 'amount': 500, 'expense_date': '2026-10-09'},
      'summary': '500 INR',
    };
    api.replies
      ..add(_answer('Shall I record an expense of 500 rupees? Please confirm.', intent: 'expense_record', propose: action))
      ..add({
        'tool': 'record_expense',
        'ok': true,
        'answer': 'Recorded: 500 rupees for fertilizer.',
        'data': {},
        'sources': <dynamic>[],
      });
    await _handsFree(tester);
    await _tapMic(tester);
    voice.say('I spent 500 rupees on fertilizer today');
    await tester.pumpAndSettle();
    expect(api.posts, hasLength(1)); // only proposed so far
    expect(find.text('Confirm'), findsOneWidget);
    expect(voice.listening, isTrue); // waiting for yes / no
    voice.say('yes');
    await tester.pumpAndSettle();
    expect(api.posts.last.$1, '/assistant/tools/record_expense');
    expect(api.posts.last.$2['confirm'], isTrue);
    expect(find.text('Recorded: 500 rupees for fertilizer.'), findsOneWidget);
    expect(find.text('Confirm'), findsNothing);
  });

  testWidgets('"no" cancels a proposal and nothing is saved', (tester) async {
    final (voice, api) = await _pump(tester);
    api.replies.add(
      _answer(
        'Shall I add this reminder? Please confirm.',
        intent: 'reminder_create',
        propose: {
          'tool': 'create_reminder',
          'args': <String, dynamic>{},
          'summary': 'x',
        },
      ),
    );
    var g = await _hold(tester);
    voice.partial('remind me to irrigate tomorrow');
    await _release(tester, g);
    g = await _hold(tester);
    voice.partial('no');
    await _release(tester, g);
    expect(api.posts, hasLength(1));
    expect(find.text('Cancelled. Nothing was saved.'), findsOneWidget);
  });

  testWidgets('cancelling while thinking ignores the late answer', (tester) async {
    final (voice, api) = await _pump(tester);
    final slow = Completer<Map<String, dynamic>>();
    api.replies.add(slow);
    await tester.enterText(find.byType(TextField), 'weather');
    await tester.tap(find.byTooltip('Send'));
    await tester.pump();
    expect(find.text('Thinking… tap to cancel'), findsOneWidget);
    await _tapMic(tester);
    expect(find.text('Cancelled.'), findsOneWidget);
    slow.complete(_answer('Too late.'));
    await tester.pumpAndSettle();
    expect(find.text('Too late.'), findsNothing);
    expect(voice.spoken, isEmpty);
  });

  testWidgets('a network failure is shown with a retry', (tester) async {
    final (_, api) = await _pump(tester);
    api.replies
      ..add(const AppFailure('network', 'Cannot reach the Harvestique server. Check your connection.'))
      ..add(_answer('Now it worked.'));
    await tester.enterText(find.byType(TextField), 'weather');
    await tester.tap(find.byTooltip('Send'));
    await tester.pumpAndSettle();
    expect(find.text('Cannot reach the Harvestique server. Check your connection.'), findsOneWidget);
    await tester.tap(find.text('Retry'));
    await tester.pumpAndSettle();
    expect(find.text('Now it worked.'), findsOneWidget);
    expect(api.posts.map((p) => p.$2['message']), ['weather', 'weather']);
  });

  testWidgets('a phone without the voice shows answers as text and says why', (tester) async {
    final (_, api) = await _pump(tester, voice: FakeVoice()..voiceInstalled = false);
    expect(find.textContaining('No English voice is installed'), findsOneWidget);
    api.replies.add(_answer('Shown as text.'));
    await tester.enterText(find.byType(TextField), 'weather');
    await tester.tap(find.byTooltip('Send'));
    await tester.pumpAndSettle();
    expect(find.text('Shown as text.'), findsOneWidget);
  });

  test('yes / no words in English and Kannada', () {
    expect(yesOrNo('yes please'), isTrue);
    expect(yesOrNo('ಹೌದು'), isTrue);
    expect(yesOrNo('ಸರಿ'), isTrue);
    expect(yesOrNo('no'), isFalse);
    expect(yesOrNo('ಬೇಡ'), isFalse);
    expect(yesOrNo('cancel it'), isFalse);
    expect(yesOrNo('what is the weather'), isNull);
  });

  testWidgets('a long question spoken in several segments is sent whole', (tester) async {
    final (voice, api) = await _pump(tester);
    api.replies.add(_answer('Here is what I found.'));
    final g = await _hold(tester);
    voice.partial('I want to know how much money');
    await tester.pump();
    voice.endSegment(); // the speaker paused: Android ended the segment while the button is still held
    await tester.pump(const Duration(milliseconds: 200));
    expect(voice.listens, 2); // listening again, same press
    voice.partial('I spent on fertilizer and labour this month');
    await tester.pump();
    voice.endSegment();
    await tester.pump(const Duration(milliseconds: 200));
    voice.partial('for my tomato crop');
    await _release(tester, g);
    expect(api.posts.single.$1, '/voice/intent');
    expect(
      api.posts.single.$2['transcript'],
      'I want to know how much money I spent on fertilizer and labour this month for my tomato crop',
    );
  });

  testWidgets('pausing while holding does not end the question', (tester) async {
    final (voice, api) = await _pump(tester);
    api.replies.add(_answer('ok'));
    final g = await _hold(tester);
    voice.partial('what is');
    await tester.pump();
    voice.fail(VoiceProblem.silence); // the recogniser timed out on a pause
    await tester.pump(const Duration(milliseconds: 200));
    expect(voice.listening, isTrue);
    voice.partial('the weather');
    await _release(tester, g);
    expect(api.posts.single.$2['transcript'], 'the weather'); // the timed-out segment had no final words
  });

  testWidgets('sliding away before release cancels and sends nothing', (tester) async {
    final (voice, api) = await _pump(tester);
    final g = await _hold(tester);
    voice.partial('delete all my farms');
    await g.moveBy(const Offset(0, -150));
    await tester.pump();
    expect(find.text('Release to cancel'), findsOneWidget);
    await _release(tester, g);
    expect(api.posts, isEmpty);
    expect(find.text('Cancelled. Nothing was sent.'), findsOneWidget);
    expect(voice.listening, isFalse);
  });

  testWidgets('a short tap explains press-and-hold instead of starting a short recording', (tester) async {
    final (voice, _) = await _pump(tester);
    await _tapMic(tester);
    expect(voice.listens, 0);
    expect(find.text('Press and hold the microphone while you speak, then let go.'), findsOneWidget);
  });

  testWidgets('holding the microphone interrupts a spoken answer and records', (tester) async {
    final voice = FakeVoice()..holdSpeech = true;
    final (_, api) = await _pump(tester, voice: voice);
    api.replies.add(_answer('A long answer.'));
    await tester.enterText(find.byType(TextField), 'weather');
    await tester.tap(find.byTooltip('Send'));
    await tester.pump();
    await tester.pump();
    final g = await _hold(tester);
    expect(voice.stopSpeakingCalls, greaterThan(0));
    expect(voice.listening, isTrue);
    await g.up();
    await tester.pumpAndSettle();
  });

  testWidgets('the recogniser\'s other readings are sent so a misheard first reading can be recovered', (tester) async {
    final (voice, api) = await _pump(tester);
    api.replies.add({..._answer('ನಾಳೆ ಮಳೆ ಇಲ್ಲ.'), 'heard': 'ನಾಳೆ ವೆದರ್ ಹೇಗಿದೆ', 'understood_by': 'alternative'});
    voice.nextAlternates = ['ನಾಳೆ ವೆದರ್ ಹೇಗಿದೆ', 'ನಾಳೆ ಮಳೆ'];
    final g = await _hold(tester);
    voice.partial('ನಾಳೆ ವೆಧರ ಹೇಗೆ');
    await _release(tester, g);
    expect(api.posts.single.$2['alternatives'], ['ನಾಳೆ ವೆದರ್ ಹೇಗಿದೆ', 'ನಾಳೆ ಮಳೆ']);
    expect(find.textContaining('ನಾಳೆ ವೆದರ್ ಹೇಗಿದೆ'), findsOneWidget); // "Understood as: ..." is shown
  });

  testWidgets('typed questions never send recogniser alternatives', (tester) async {
    final (voice, api) = await _pump(tester);
    voice.nextAlternates = ['should not be sent'];
    api.replies.add(_answer('ok'));
    await tester.enterText(find.byType(TextField), 'what is the weather');
    await tester.tap(find.byTooltip('Send'));
    await tester.pumpAndSettle();
    expect(api.posts.single.$2.containsKey('alternatives'), isFalse);
  });

  testWidgets('a spoken navigation command switches the shell tab the server named', (tester) async {
    final (_, api) = await _pump(tester);
    api.replies.add({..._answer('Opening Market.'), 'intent': 'navigate', 'navigate_to': 'market'});
    await tester.enterText(find.byType(TextField), 'open market');
    await tester.tap(find.byTooltip('Send'));
    await tester.pumpAndSettle();
    final container = ProviderScope.containerOf(tester.element(find.byType(MaterialApp)));
    expect(container.read(shellTabRequestProvider), 'market');
  });

  testWidgets('an unknown navigation key from the server is ignored', (tester) async {
    final (_, api) = await _pump(tester);
    api.replies.add({..._answer('Opening.'), 'intent': 'navigate', 'navigate_to': 'admin_console'});
    await tester.enterText(find.byType(TextField), 'open admin');
    await tester.tap(find.byTooltip('Send'));
    await tester.pumpAndSettle();
    final container = ProviderScope.containerOf(tester.element(find.byType(MaterialApp)));
    expect(container.read(shellTabRequestProvider), isNull);
    expect(find.byType(AssistantScreen), findsOneWidget);
  });

  testWidgets('choosing Kannada on a phone without a Kannada recogniser says so', (tester) async {
    final (_, _) = await _pump(tester, voice: FakeVoice()..knRecognizer = false);
    await tester.tap(find.text('ಕನ್ನಡ'));
    await tester.pumpAndSettle();
    expect(find.textContaining('does not list Kannada'), findsOneWidget);
  });

  testWidgets('tapping Send twice while the first question is in flight asks the server once', (tester) async {
    final (_, api) = await _pump(tester);
    final slow = Completer<Map<String, dynamic>>();
    api.replies.add(slow);
    await tester.enterText(find.byType(TextField), 'what crops are best to grow on my farm?');
    await tester.tap(find.byTooltip('Send'));
    await tester.pump();
    await tester.enterText(find.byType(TextField), 'what crops are best to grow on my farm?');
    await tester.tap(find.byTooltip('Send'));
    await tester.pump();
    expect(api.posts, hasLength(1));
    slow.complete(_answer('Crops to consider ...'));
    await tester.pumpAndSettle();
    expect(find.text('Crops to consider ...'), findsOneWidget);
  });

  testWidgets('a double tap on Confirm saves once', (tester) async {
    final (_, api) = await _pump(tester);
    final save = Completer<Map<String, dynamic>>();
    api.replies
      ..add(_answer('Shall I add this reminder? Please confirm.', intent: 'reminder_create', propose: {
        'tool': 'create_reminder',
        'args': <String, dynamic>{'title': 'Water'},
        'summary': 'x',
      },),)
      ..add(save);
    await tester.enterText(find.byType(TextField), 'remind me to water tomorrow');
    await tester.tap(find.byTooltip('Send'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Confirm'));
    await tester.pump();
    if (find.text('Confirm').evaluate().isNotEmpty) await tester.tap(find.text('Confirm'), warnIfMissed: false);
    await tester.pump();
    expect(api.posts.where((p) => p.$1.startsWith('/assistant/tools/')), hasLength(1));
    save.complete({'tool': 'create_reminder', 'ok': true, 'answer': 'Added.', 'data': {}, 'sources': <dynamic>[]});
    await tester.pumpAndSettle();
  });

  testWidgets('voice details show the raw recogniser text, alternatives, what was sent and what the server read',
      (tester) async {
    final (voice, api) = await _pump(tester);
    await tester.tap(find.text('ಕನ್ನಡ'));
    await tester.pumpAndSettle();
    api.replies.add({
      ..._answer('ಸರಿ, ನೀವು ಮಾವು ಬೆಳೆಯುತ್ತಿದ್ದೀರಿ.', intent: 'crop_statement'),
      'normalised': 'ನಾನು ನನ್ನ ಜಮೀನಿನಲ್ಲಿ ಮಾವು ಬೆಳೆಯುತ್ತಿದ್ದೇನೆ',
      'understood_by': 'rules',
    });
    voice.nextAlternates = ['ನಾನು ನನ್ನ ಜಮೀನಿನಲ್ಲಿ ಮಾವು ಬೆಳೆಯುತ್ತೇನೆ'];
    final g = await _hold(tester);
    voice.partial('ನಾನು ನನ್ನ ಜಮೀನಿನಲ್ಲಿ ಮಾವು ಬೆಳೆಯುತ್ತಿದ್ದೇನೆ.');
    await _release(tester, g);
    expect(api.posts.single.$2['transcript'], 'ನಾನು ನನ್ನ ಜಮೀನಿನಲ್ಲಿ ಮಾವು ಬೆಳೆಯುತ್ತಿದ್ದೇನೆ.');
    await tester.tap(find.text('Voice details'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Recogniser (kn_IN): ನಾನು ನನ್ನ ಜಮೀನಿನಲ್ಲಿ ಮಾವು ಬೆಳೆಯುತ್ತಿದ್ದೇನೆ.'), findsOneWidget);
    expect(find.textContaining('Other readings: ನಾನು ನನ್ನ ಜಮೀನಿನಲ್ಲಿ ಮಾವು ಬೆಳೆಯುತ್ತೇನೆ'), findsOneWidget);
    expect(find.textContaining('Server read: ನಾನು ನನ್ನ ಜಮೀನಿನಲ್ಲಿ ಮಾವು ಬೆಳೆಯುತ್ತಿದ್ದೇನೆ'), findsOneWidget);
    expect(find.textContaining('Understood as: crop_statement (rules)'), findsOneWidget);
  });

  test('a Kannada voice is taken from Google TTS when the default engine has none', () async {
    final checked = <String>[];
    Future<bool> has(String engine) async {
      checked.add(engine);
      return engine == 'com.google.android.tts';
    }

    expect(await pickTtsEngine(defaultEngine: 'com.samsung.SMT', engines: ['com.samsung.SMT', 'com.google.android.tts'], hasLanguage: has),
        'com.google.android.tts',);
    expect(checked, ['com.samsung.SMT', 'com.google.android.tts']);
    expect(await pickTtsEngine(defaultEngine: 'com.samsung.SMT', engines: ['com.samsung.SMT'], hasLanguage: has), isNull);
    expect(await pickTtsEngine(defaultEngine: 'com.google.android.tts', engines: const [], hasLanguage: has),
        'com.google.android.tts',);
  });
}
