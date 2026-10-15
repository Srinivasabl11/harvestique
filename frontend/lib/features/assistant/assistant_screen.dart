import 'dart:async';

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/network/api_client.dart';
import '../../core/util/json.dart';
import '../../core/widgets/common.dart';
import '../auth/auth_controller.dart';
import '../crop_health/crop_health_screen.dart';
import '../notifications/notifications_screen.dart';
import '../planning/plans_screen.dart';
import '../shell/shell_navigation.dart';
import 'voice_engine.dart';

/// Ask Harvestique: a voice-first farm assistant (English / Kannada) that answers from the farmer's own records
/// through controlled server tools.
///
/// * Speech recognition and speech output run ON THE PHONE (free; see [VoiceEngine]); only text goes to the server.
/// * Conversation mode listens again after each answer while this screen is open (Android does not allow an app to
///   keep listening in the background, and there is no wake word).
/// * Anything that saves data (a reminder, an expense) is only proposed; it is saved after "yes" or a Confirm tap,
///   and the server refuses it without that confirmation.
class AssistantScreen extends ConsumerStatefulWidget {
  const AssistantScreen({super.key});

  @override
  ConsumerState<AssistantScreen> createState() => _AssistantScreenState();
}

enum _Phase { idle, listening, thinking, speaking }

class _Turn {
  _Turn.user(this.text)
      : fromUser = true,
        reply = null,
        retry = null;
  _Turn.bot(Map<String, dynamic> this.reply, {this.voice})
      : fromUser = false,
        text = reply.str('answer'),
        retry = null;
  _Turn.error(this.text, this.retry)
      : fromUser = false,
        reply = null;

  final bool fromUser;
  final String text;
  final Map<String, dynamic>? reply;
  final String? retry; // the question to ask again after a failure
  _VoiceInfo? voice; // spoken questions only: what the recogniser gave, for checking on the phone
  bool confirmed = false;
  bool cancelled = false;

  bool get pending => reply != null && reply!.boolVal('requires_confirmation') && !confirmed && !cancelled;
}

/// What the phone's recogniser produced for a spoken question, shown under the answer ("Voice details") so a wrong
/// answer can be traced to the recogniser, the text sent, or the server's reading of it.
class _VoiceInfo {
  const _VoiceInfo(this.locale, this.raw, this.alternates);

  final String locale;
  final String raw;
  final List<String> alternates;
}

final _yes = RegExp(r'\b(yes|yeah|yep|confirm|ok|okay|sure|haan|han|ha)\b|ಹೌದು|ಸರಿ|ಆಯ್ತು|ಹಾಂ');
final _no = RegExp(r"\b(no|nope|cancel|don't|do not|stop)\b|ಬೇಡ|ಇಲ್ಲ|ರದ್ದು");
final _quit = RegExp(r'^(stop|bye|goodbye|thank you|thanks|that.?s all)\b|ನಿಲ್ಲಿಸು|ಸಾಕು|ಧನ್ಯವಾದ');

/// "yes" -> true, "no" -> false, anything else -> null.
bool? yesOrNo(String words) {
  final w = words.toLowerCase();
  if (_no.hasMatch(w)) return false;
  if (_yes.hasMatch(w)) return true;
  return null;
}

class _AssistantScreenState extends ConsumerState<AssistantScreen> with WidgetsBindingObserver {
  late final VoiceEngine _voice = ref.read(voiceEngineProvider);
  final _input = TextEditingController();
  final _scroll = ScrollController();
  final _turns = <_Turn>[];
  late String _lang = ref.read(authProvider).language;
  _Phase _phase = _Phase.idle;
  bool _speechReady = false;
  bool _speakReplies = true;
  bool _handsFree = false;
  bool _offlineOnly = false;
  bool _voiceInstalled = true;
  int _silences = 0;
  int _request = 0; // bumps on cancel: a late reply to a cancelled question is ignored
  String? _notice;
  List<String> _alternates = const []; // the recogniser's other readings of the last speech

  // press-and-hold dictation
  bool _holdMode = false; // the current listening was started by holding the microphone
  bool _holding = false; // the finger is still on the button
  bool _cancelHold = false; // slid away: releasing cancels
  bool _restartPending = false;
  final _segments = <String>[]; // finished recogniser segments while held
  String _partial = ''; // the segment being recognised now
  Completer<void>? _finalWait;
  DateTime? _holdStart;
  Timer? _holdTimer;

  String get _transcript => [..._segments, if (_partial.trim().isNotEmpty) _partial.trim()].join(' ');

  bool get _kn => _lang == 'kn';

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _initSpeech();
    _checkVoice();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.paused || state == AppLifecycleState.inactive || state == AppLifecycleState.hidden) {
      _stopAll(); // never keep the microphone open in the background
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _holdTimer?.cancel();
    _voice.cancelListening();
    _voice.stopSpeaking();
    _input.dispose();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _initSpeech() async {
    final ok = await _voice.init(onError: _onVoiceError, onDone: _onListenDone);
    if (!mounted) return;
    setState(() {
      _speechReady = ok;
      if (!ok) {
        _notice = 'Speech recognition is not available: the microphone permission was refused or this phone has no '
            'speech recogniser. You can type your question.';
      }
    });
    if (ok) await _checkRecognizer();
  }

  /// Kannada needs a Kannada speech recogniser on the phone; without one Android silently recognises English.
  Future<void> _checkRecognizer() async {
    if (!_kn || !_speechReady) return;
    final ok = await _voice.hasRecognizer('kn');
    if (!mounted || ok || !_kn) return;
    setState(
      () => _notice = 'This phone\'s speech recogniser does not list Kannada, so spoken Kannada may be heard as '
          'English. Add Kannada in Android Settings > Google > voice typing / speech languages, or type in Kannada.',
    );
  }

  Future<void> _checkVoice() async {
    final ok = await _voice.hasVoice(_lang);
    if (mounted) setState(() => _voiceInstalled = ok);
  }

  void _stopAll() {
    _voice.cancelListening();
    _voice.stopSpeaking();
    _holdTimer?.cancel();
    if (!mounted) return;
    setState(() {
      _handsFree = false;
      _holdMode = false;
      _holding = false;
      if (_phase == _Phase.listening || _phase == _Phase.speaking) _phase = _Phase.idle;
    });
  }

  // ---------------------------------------------------------------- listening
  Future<void> _startListening() async {
    if (!_speechReady) return;
    await _voice.stopSpeaking(); // interrupting an answer
    if (!mounted) return;
    _input.clear();
    _alternates = const [];
    setState(() {
      _phase = _Phase.listening;
      _notice = null;
    });
    try {
      await _voice.listen(
        localeId: _kn ? 'kn_IN' : 'en_IN',
        offlineOnly: _offlineOnly,
        onAlternates: (a) => _alternates = a,
        onResult: (words, isFinal) {
          if (!mounted || _phase != _Phase.listening) return;
          _input.text = words;
          if (!isFinal) return;
          setState(() => _phase = _Phase.idle);
          if (words.trim().isEmpty) {
            _onVoiceError(VoiceProblem.silence);
          } else {
            _silences = 0;
            _heard(words.trim());
          }
        },
      );
    } catch (_) {
      _onVoiceError(VoiceProblem.other);
    }
  }

  // ------------------------------------------------------- press and hold
  Future<void> _holdBegin() async {
    if (!_speechReady || _phase == _Phase.thinking) return;
    await _voice.stopSpeaking(); // holding the button also interrupts an answer
    if (!mounted) return;
    _segments.clear();
    _partial = '';
    _input.clear();
    _alternates = const [];
    _holdTimer?.cancel();
    setState(() {
      _holdMode = true;
      _holding = true;
      _cancelHold = false;
      _holdStart = DateTime.now();
      _notice = null;
    });
    _holdTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted && _holding) setState(() {});
    });
    await _listenSegment();
  }

  Future<void> _listenSegment() async {
    if (!mounted || !_holding) return;
    setState(() => _phase = _Phase.listening);
    try {
      await _voice.listen(
        localeId: _kn ? 'kn_IN' : 'en_IN',
        offlineOnly: _offlineOnly,
        longForm: true,
        onAlternates: (a) => _alternates = a,
        onResult: (words, isFinal) {
          if (!mounted || !_holdMode) return;
          setState(() {
            if (isFinal) {
              if (words.trim().isNotEmpty) _segments.add(words.trim());
              _partial = '';
            } else {
              _partial = words;
            }
            _input.text = _transcript;
          });
          if (isFinal && !_holding && !(_finalWait?.isCompleted ?? true)) _finalWait!.complete();
        },
      );
    } catch (_) {
      _holdFailed(VoiceProblem.other);
    }
  }

  /// The recogniser ended a segment (pause) while the button is still held: start the next one.
  Future<void> _restartSegment() async {
    if (_restartPending) return;
    _restartPending = true;
    await Future<void>.delayed(const Duration(milliseconds: 150));
    _restartPending = false;
    if (mounted && _holding && !_voice.isListening) await _listenSegment();
  }

  void _holdMoved(Offset fromOrigin) {
    final cancel = fromOrigin.dy < -80 || fromOrigin.dx.abs() > 120;
    if (cancel != _cancelHold) setState(() => _cancelHold = cancel);
  }

  Future<void> _holdEnd() async {
    if (!_holdMode || !_holding) return;
    _holdTimer?.cancel();
    setState(() => _holding = false);
    if (_cancelHold) {
      await _voice.cancelListening();
      if (!mounted) return;
      setState(() {
        _holdMode = false;
        _phase = _Phase.idle;
        _input.clear();
        _notice = _kn ? 'ರದ್ದುಗೊಳಿಸಲಾಗಿದೆ. ಏನೂ ಕಳುಹಿಸಲಾಗಿಲ್ಲ.' : 'Cancelled. Nothing was sent.';
      });
      return;
    }
    _finalWait = Completer<void>();
    await _voice.stopListening(); // the recogniser delivers the last words as a final result
    await _finalWait!.future.timeout(const Duration(seconds: 3), onTimeout: () {});
    if (!mounted) return;
    final text = _transcript.trim();
    setState(() {
      _holdMode = false;
      _phase = _Phase.idle;
    });
    if (text.isEmpty) {
      setState(
        () => _notice = _kn
            ? 'ನನಗೆ ಏನೂ ಕೇಳಿಸಲಿಲ್ಲ. ಮಾತನಾಡುವಾಗ ಮೈಕ್ ಒತ್ತಿ ಹಿಡಿಯಿರಿ.'
            : "I didn't hear anything. Keep holding the microphone while you speak.",
      );
      return;
    }
    _heard(text);
  }

  void _holdFailed(VoiceProblem problem) {
    _holdTimer?.cancel();
    setState(() {
      _holdMode = false;
      _holding = false;
      _phase = _Phase.idle;
    });
    _showProblem(problem);
  }

  void _onListenDone() {
    if (_holdMode) {
      if (_holding) {
        _restartSegment();
      } else if (!(_finalWait?.isCompleted ?? true)) {
        _finalWait!.complete();
      }
      return;
    }
    // the recogniser stopped; a final result or an error normally follows, this only covers a silent stop
    if (mounted && _phase == _Phase.listening && _input.text.trim().isEmpty) {
      Future<void>.delayed(const Duration(milliseconds: 400), () {
        if (mounted && _phase == _Phase.listening && _input.text.trim().isEmpty) _onVoiceError(VoiceProblem.silence);
      });
    }
  }

  void _onVoiceError(VoiceProblem problem) {
    if (!mounted) return;
    if (_holdMode) {
      if (problem == VoiceProblem.silence || problem == VoiceProblem.noMatch) {
        // a pause while holding is normal: keep listening; after release, finish with what was heard
        if (_holding) {
          _restartSegment();
        } else if (!(_finalWait?.isCompleted ?? true)) {
          _finalWait!.complete();
        }
      } else {
        _holdFailed(problem);
      }
      return;
    }
    if (_phase != _Phase.listening) return;
    setState(() => _phase = _Phase.idle);
    if (problem == VoiceProblem.silence || problem == VoiceProblem.noMatch) {
      _silences += 1;
      if (_handsFree && _silences < 2) {
        _startListening();
        return;
      }
    }
    _showProblem(problem);
  }

  void _showProblem(VoiceProblem problem) {
    switch (problem) {
      case VoiceProblem.silence:
      case VoiceProblem.noMatch:
        setState(() {
          if (_handsFree) _handsFree = false;
          _notice = problem == VoiceProblem.silence
              ? (_kn
                  ? 'ನನಗೆ ಏನೂ ಕೇಳಿಸಲಿಲ್ಲ. ಮೈಕ್ ಒತ್ತಿ ಮತ್ತೆ ಹೇಳಿ.'
                  : "I didn't hear anything. Tap the microphone and try again.")
              : (_kn
                  ? 'ನನಗೆ ಅರ್ಥವಾಗಲಿಲ್ಲ. ಮತ್ತೆ ಹೇಳಿ ಅಥವಾ ಟೈಪ್ ಮಾಡಿ.'
                  : "I couldn't make that out. Please say it again or type it.");
        });
      case VoiceProblem.permission:
        setState(() {
          _speechReady = false;
          _handsFree = false;
          _notice = 'Microphone permission is off. Allow it in Android Settings > Apps > Harvestique > Permissions, '
              'or type your question.';
        });
      case VoiceProblem.network:
        setState(() {
          _handsFree = false;
          _notice = 'Speech recognition could not reach the speech service. Connect to the internet, or install the '
              '${_kn ? 'Kannada' : 'English (India)'} offline speech pack on the phone, or type your question.';
        });
      case VoiceProblem.other:
        setState(() {
          _handsFree = false;
          _notice = 'The microphone is busy or stopped working. Try again, or type your question.';
        });
    }
  }

  void _heard(String words) {
    if (_handsFree && _quit.hasMatch(words.toLowerCase())) {
      setState(() {
        _handsFree = false;
        _turns.add(_Turn.user(words));
        _turns.add(_Turn.bot({'answer': _kn ? 'ಸರಿ, ಸಂಭಾಷಣೆ ಮೋಡ್ ನಿಲ್ಲಿಸಲಾಗಿದೆ.' : 'Okay, conversation mode is off.'}));
      });
      return;
    }
    final pending = _turns.lastWhere((t) => t.pending, orElse: () => _Turn.user(''));
    if (pending.pending) {
      final answer = yesOrNo(words);
      if (answer != null) {
        setState(() => _turns.add(_Turn.user(words)));
        answer ? _confirm(pending) : _cancel(pending);
        return;
      }
    }
    _send(words, voice: true);
  }

  /// A short tap: interrupts an answer, cancels a question in progress, stops conversation-mode listening, or
  /// explains press-and-hold.
  Future<void> _micTapped() async {
    if (_phase == _Phase.idle && !_handsFree) {
      setState(
        () => _notice = _kn
            ? 'ಮಾತನಾಡುವಾಗ ಮೈಕ್ ಅನ್ನು ಒತ್ತಿ ಹಿಡಿಯಿರಿ, ಮುಗಿದ ನಂತರ ಬಿಡಿ.'
            : 'Press and hold the microphone while you speak, then let go.',
      );
      return;
    }
    if (_phase == _Phase.speaking) {
      await _voice.stopSpeaking();
      if (mounted) setState(() => _phase = _Phase.idle);
      return;
    }
    await _micPressed();
  }

  Future<void> _micPressed() async {
    switch (_phase) {
      case _Phase.idle:
        _silences = 0;
        await _startListening();
      case _Phase.listening:
        await _voice.stopListening(); // finishes with what was heard so far
      case _Phase.thinking:
        setState(() {
          _request += 1; // ignore the answer that is still on its way
          _phase = _Phase.idle;
          _turns.add(_Turn.error(_kn ? 'ರದ್ದುಗೊಳಿಸಲಾಗಿದೆ.' : 'Cancelled.', null));
        });
      case _Phase.speaking:
        _silences = 0;
        await _startListening(); // interrupt the answer and listen
    }
  }

  // ---------------------------------------------------------------- asking
  List<Map<String, dynamic>> _history() {
    final out = <Map<String, dynamic>>[];
    for (final t in _turns) {
      if (t.text.isEmpty || (!t.fromUser && t.reply == null)) continue;
      final text = t.text.length > 1200 ? t.text.substring(0, 1200) : t.text;
      out.add(
        t.fromUser
            ? {'role': 'user', 'text': text}
            : {'role': 'assistant', 'text': text, if (t.reply!.str('intent').isNotEmpty) 'intent': t.reply!.str('intent')},
      );
    }
    return out.length > 8 ? out.sublist(out.length - 8) : out;
  }

  Future<void> _send(String text, {bool voice = false}) async {
    final message = text.trim();
    if (message.isEmpty || _phase == _Phase.thinking) return;
    if (message.length > 1000) {
      setState(() => _notice = 'That is ${message.length} characters; please ask in fewer words (1000 at most).');
      return;
    }
    final history = _history();
    // alternatives describe ONE recogniser segment: only sent when the whole question was a single segment
    final alternates = voice && _segments.length <= 1 ? _alternates : const <String>[];
    final voiceInfo = voice ? _VoiceInfo(_kn ? 'kn_IN' : 'en_IN', text, alternates) : null;
    _alternates = const [];
    final id = ++_request;
    _input.clear();
    setState(() {
      _turns.add(_Turn.user(message));
      _phase = _Phase.thinking;
      _notice = null;
    });
    _scrollDown();
    try {
      final reply = await ref.read(apiProvider).ask(
        voice ? '/voice/intent' : '/assistant/chat',
        {
          voice ? 'transcript' : 'message': message,
          'language': _lang,
          'history': history,
          if (alternates.isNotEmpty) 'alternatives': alternates.map((a) => a.length > 1000 ? a.substring(0, 1000) : a).toList(),
        },
      );
      if (!mounted || id != _request) return;
      setState(() {
        _turns.add(_Turn.bot(reply, voice: voiceInfo));
        _phase = _Phase.idle;
      });
      _scrollDown();
      await _say(reply.str('answer'), reply.str('language', _lang));
      final target = reply.str('navigate_to');
      if (target.isNotEmpty && mounted && id == _request) _openScreen(target);
    } catch (e) {
      if (!mounted || id != _request) return;
      final f = mapDioError(e);
      setState(() {
        _turns.add(_Turn.error(f.message, message));
        _phase = _Phase.idle;
        _handsFree = false; // do not keep listening into a broken connection
      });
      _scrollDown();
    }
  }

  /// Opens a screen the server named from its allowlist. Tabs are switched by the shell; anything unknown is ignored.
  void _openScreen(String target) {
    final nav = Navigator.of(context);
    _stopAll();
    switch (target) {
      case 'back':
        nav.maybePop();
      case 'crop_health':
        nav.pushReplacement(MaterialPageRoute<void>(builder: (_) => const CropHealthScreen()));
      case 'planning':
        nav.pushReplacement(MaterialPageRoute<void>(builder: (_) => const PlansScreen()));
      case 'notifications':
        nav.pushReplacement(MaterialPageRoute<void>(builder: (_) => const NotificationsScreen()));
      default:
        if (!farmerTabs.containsKey(target) && !buyerTabs.containsKey(target)) return;
        ref.read(shellTabRequestProvider.notifier).state = target;
        nav.maybePop();
    }
  }

  Future<void> _say(String text, String language) async {
    if (_speakReplies && text.isNotEmpty) {
      setState(() => _phase = _Phase.speaking);
      final spoken = await _voice.speak(text, language);
      if (!mounted || _phase != _Phase.speaking) return; // interrupted by the microphone
      setState(() {
        _phase = _Phase.idle;
        if (!spoken) {
          _voiceInstalled = false;
          _notice = 'No ${language == 'kn' ? 'Kannada' : 'English'} voice is installed on this phone, so answers are '
              'shown as text. Install it in Android Settings > Text-to-speech.';
        }
      });
    }
    if (_handsFree && _speechReady && mounted && _phase == _Phase.idle) await _startListening();
  }

  Future<void> _confirm(_Turn turn) async {
    final action = turn.reply!.obj('proposed_action');
    setState(() => _phase = _Phase.thinking);
    try {
      final res = await ref.read(apiProvider).post(
        '/assistant/tools/${action.str('tool')}',
        body: {'args': action.obj('args'), 'confirm': true, 'language': _lang},
      );
      if (!mounted) return;
      setState(() {
        turn.confirmed = true;
        _phase = _Phase.idle;
        _turns.add(_Turn.bot({'answer': res.str('answer'), 'intent': '', 'answer_kind': 'records'}));
      });
      _scrollDown();
      await _say(res.str('answer'), _lang);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _phase = _Phase.idle;
        _turns.add(_Turn.error('${_kn ? 'ಉಳಿಸಲಾಗಲಿಲ್ಲ' : 'Not saved'}: ${mapDioError(e).message}', null));
      });
    }
  }

  Future<void> _cancel(_Turn turn) async {
    final text = _kn ? 'ರದ್ದುಗೊಳಿಸಲಾಗಿದೆ. ಏನೂ ಉಳಿಸಲಾಗಿಲ್ಲ.' : 'Cancelled. Nothing was saved.';
    setState(() {
      turn.cancelled = true;
      _turns.add(_Turn.bot({'answer': text}));
    });
    await _say(text, _lang);
  }

  void _scrollDown() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) {
        _scroll.animateTo(_scroll.position.maxScrollExtent, duration: const Duration(milliseconds: 200), curve: Curves.easeOut);
      }
    });
  }

  // ---------------------------------------------------------------- UI
  String get _elapsed {
    final s = _holdStart == null ? 0 : DateTime.now().difference(_holdStart!).inSeconds;
    return '${s ~/ 60}:${(s % 60).toString().padLeft(2, '0')}';
  }

  String get _status => switch (_phase) {
        _ when _holdMode && _cancelHold => _kn ? 'ಬಿಟ್ಟರೆ ರದ್ದಾಗುತ್ತದೆ' : 'Release to cancel',
        _ when _holdMode && _holding => _kn
            ? 'ರೆಕಾರ್ಡಿಂಗ್ $_elapsed · ಕಳುಹಿಸಲು ಬಿಡಿ · ರದ್ದುಗೊಳಿಸಲು ಮೇಲೆ ಸರಿಸಿ'
            : 'Recording $_elapsed · release to send · slide up to cancel',
        _ when _holdMode => _kn ? 'ಮುಗಿಸುತ್ತಿದ್ದೇನೆ…' : 'Finishing…',
        _Phase.idle =>
          _speechReady ? (_kn ? 'ಮಾತನಾಡುವಾಗ ಮೈಕ್ ಒತ್ತಿ ಹಿಡಿಯಿರಿ' : 'Hold the microphone while you speak') : 'Type your question',
        _Phase.listening => _kn ? 'ಕೇಳುತ್ತಿದ್ದೇನೆ… ನಿಲ್ಲಿಸಲು ಒತ್ತಿ' : 'Listening… tap to stop',
        _Phase.thinking => _kn ? 'ಯೋಚಿಸುತ್ತಿದ್ದೇನೆ… ರದ್ದುಗೊಳಿಸಲು ಒತ್ತಿ' : 'Thinking… tap to cancel',
        _Phase.speaking => _kn ? 'ಮಾತನಾಡುತ್ತಿದ್ದೇನೆ… ತಡೆಯಲು ಒತ್ತಿ' : 'Speaking… tap to interrupt',
      };

  IconData get _micIcon => switch (_phase) {
        _Phase.idle => Icons.mic,
        _Phase.listening => Icons.stop,
        _Phase.thinking => Icons.close,
        _Phase.speaking => Icons.mic,
      };

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Ask Harvestique'),
        actions: [
          SegmentedButton<String>(
            showSelectedIcon: false,
            segments: const [ButtonSegment(value: 'en', label: Text('EN')), ButtonSegment(value: 'kn', label: Text('ಕನ್ನಡ'))],
            selected: {_lang},
            onSelectionChanged: (s) {
              setState(() => _lang = s.first);
              _checkVoice();
              _checkRecognizer();
            },
          ),
          IconButton(
            tooltip: _speakReplies ? 'Mute spoken replies' : 'Speak replies',
            icon: Icon(_speakReplies ? Icons.volume_up : Icons.volume_off),
            onPressed: () {
              if (_speakReplies) _voice.stopSpeaking();
              setState(() {
                _speakReplies = !_speakReplies;
                if (_phase == _Phase.speaking) _phase = _Phase.idle;
              });
            },
          ),
          PopupMenuButton<String>(
            tooltip: 'Voice settings',
            onSelected: (v) => setState(() {
              if (v == 'handsfree') _handsFree = !_handsFree;
              if (v == 'offline') _offlineOnly = !_offlineOnly;
              if (v == 'clear') _turns.clear();
            }),
            itemBuilder: (context) => [
              CheckedPopupMenuItem(
                value: 'handsfree',
                checked: _handsFree,
                enabled: _speechReady,
                child: const Text('Conversation mode (listen again after each answer)'),
              ),
              CheckedPopupMenuItem(value: 'offline', checked: _offlineOnly, child: const Text('Offline speech recognition only')),
              const PopupMenuItem(value: 'clear', child: Text('Clear conversation')),
              const PopupMenuItem(
                enabled: false,
                child: Text(
                  "Speech uses this phone's own recogniser and voices. English (India) and Kannada work only if they "
                  'are installed (Settings > Languages / Text-to-speech); offline use needs the offline packs.',
                  style: TextStyle(fontSize: 12),
                ),
              ),
            ],
          ),
        ],
      ),
      body: Column(
        children: [
          if (_notice != null)
            MaterialBanner(
              backgroundColor: scheme.errorContainer,
              content: Text(_notice!, style: TextStyle(color: scheme.onErrorContainer)),
              actions: [TextButton(onPressed: () => setState(() => _notice = null), child: const Text('OK'))],
            )
          else if (!_voiceInstalled && _speakReplies)
            MaterialBanner(
              content: Text('No ${_kn ? 'Kannada' : 'English'} voice is installed on this phone: answers are shown as text.'),
              actions: const [SizedBox.shrink()],
            ),
          Expanded(
            child: _turns.isEmpty
                ? EmptyPanel(
                    icon: Icons.mic_none,
                    message: _kn
                        ? 'ಹವಾಮಾನ, ಕೊಯ್ಲು ಅಂದಾಜು, ಖರ್ಚು, ಆದಾಯ ಯೋಜನೆ, ಜ್ಞಾಪನೆ, ದಾಸ್ತಾನು ಅಥವಾ ಖರೀದಿದಾರರ ಬಗ್ಗೆ ಕೇಳಿ.\n'
                            'ಉದಾ: "ಈ ತಿಂಗಳು ಎಷ್ಟು ಖರ್ಚು ಆಗಿದೆ?" ಅಥವಾ "ನಾಳೆ ಮಳೆ ಬರುತ್ತದೆಯೇ?"'
                        : 'Ask about weather, harvest predictions, expenses, income plans, reminders, stock or buyers.\n'
                            'Try: "How much did I spend this month?", "I spent 500 rupees on fertilizer today" or '
                            '"Remind me to irrigate tomorrow at 6 am".\nAdvice only, from your own records.',
                  )
                : ListView.builder(
                    controller: _scroll,
                    padding: const EdgeInsets.all(12),
                    itemCount: _turns.length,
                    itemBuilder: (context, i) => _bubble(context, _turns[i]),
                  ),
          ),
          if (_phase == _Phase.thinking) const LinearProgressIndicator(),
          SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(8, 8, 8, 4),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      if (_handsFree) const Chip(avatar: Icon(Icons.all_inclusive, size: 18), label: Text('Conversation mode')),
                      const SizedBox(width: 8),
                      Flexible(child: Text(_status, style: Theme.of(context).textTheme.bodyMedium)),
                    ],
                  ),
                  const SizedBox(height: 8),
                  if (_holdMode && _transcript.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 6),
                      child: Text(_transcript, textAlign: TextAlign.center, maxLines: 3, overflow: TextOverflow.ellipsis),
                    ),
                  Semantics(
                    label: _speechReady ? 'Microphone. Press and hold to speak, release to send.' : 'Microphone unavailable',
                    child: RawGestureDetector(
                      gestures: {
                        if (_speechReady)
                          LongPressGestureRecognizer: GestureRecognizerFactoryWithHandlers<LongPressGestureRecognizer>(
                            () => LongPressGestureRecognizer(duration: const Duration(milliseconds: 200)),
                            (r) => r
                              ..onLongPressStart = ((_) => _holdBegin())
                              ..onLongPressMoveUpdate = ((d) => _holdMoved(d.localOffsetFromOrigin))
                              ..onLongPressEnd = ((_) => _holdEnd())
                              ..onLongPressCancel = _holdEnd,
                          ),
                      },
                      child: SizedBox(
                        width: 84,
                        height: 84,
                        child: FloatingActionButton.large(
                          heroTag: 'assistant-mic',
                          tooltip: _speechReady ? _status : 'Speech recognition is not available on this phone',
                          backgroundColor: _cancelHold && _holding
                              ? scheme.outline
                              : (_phase == _Phase.listening ? scheme.error : scheme.primary),
                          foregroundColor: _phase == _Phase.listening ? scheme.onError : scheme.onPrimary,
                          onPressed: _speechReady || _phase == _Phase.thinking ? _micTapped : null,
                          child: Icon(_holdMode && _holding ? Icons.mic : _micIcon, size: 40),
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      Expanded(
                        child: TextField(
                          controller: _input,
                          minLines: 1,
                          maxLines: 3,
                          maxLength: 1000,
                          textInputAction: TextInputAction.send,
                          onSubmitted: (t) => _send(t),
                          decoration: InputDecoration(
                            hintText: _phase == _Phase.listening ? 'Listening…' : 'Or type your question',
                            counterText: '',
                          ),
                        ),
                      ),
                      IconButton(
                        tooltip: 'Send',
                        onPressed: _phase == _Phase.thinking ? null : () => _send(_input.text),
                        icon: const Icon(Icons.send),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  /// Raw recogniser text, its other readings, what was sent and what the server read. No account data or tokens.
  Widget _voiceDetails(BuildContext context, Map<String, dynamic> r, _VoiceInfo v) {
    final small = Theme.of(context).textTheme.bodySmall;
    final how = r.str('understood_by');
    final lines = [
      'Recogniser (${v.locale}): ${v.raw}',
      if (v.alternates.isNotEmpty) 'Other readings: ${v.alternates.join(' | ')}',
      'Sent: transcript${v.alternates.isEmpty ? '' : ' + ${v.alternates.length} other reading(s)'}',
      if (r.str('normalised').isNotEmpty) 'Server read: ${r.str('normalised')}',
      'Understood as: ${r.str('intent', 'unknown')}${how.isEmpty ? '' : ' ($how)'}',
      if (_voice.ttsEngine != null) 'Voice used: ${_voice.ttsEngine}',
    ];
    // its own transparent Material: the bubble's coloured box would otherwise hide the tile's ink
    return Material(
      type: MaterialType.transparency,
      child: ExpansionTile(
        title: Text('Voice details', style: small),
        tilePadding: EdgeInsets.zero,
        childrenPadding: const EdgeInsets.only(bottom: 4),
        dense: true,
        expandedCrossAxisAlignment: CrossAxisAlignment.start,
        children: [for (final l in lines) SelectableText(l, style: small)],
      ),
    );
  }

  Widget _bubble(BuildContext context, _Turn t) {
    final scheme = Theme.of(context).colorScheme;
    final r = t.reply;
    final isError = !t.fromUser && r == null;
    return Align(
      alignment: t.fromUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 4),
        padding: const EdgeInsets.all(12),
        constraints: const BoxConstraints(maxWidth: 340),
        decoration: BoxDecoration(
          color: t.fromUser ? scheme.primaryContainer : (isError ? scheme.errorContainer : scheme.surfaceContainerHighest),
          borderRadius: BorderRadius.circular(14),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (r != null && r.str('heard').isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Text(
                  '${_kn ? 'ಹೀಗೆ ಅರ್ಥಮಾಡಿಕೊಂಡೆ' : 'Understood as'}: "${r.str('heard')}"',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ),
            Text(t.text, style: const TextStyle(fontSize: 16)),
            if (r != null && (r.objs('sources').isNotEmpty || r.str('answer_kind') == 'general_ai')) ...[
              const SizedBox(height: 6),
              Wrap(
                spacing: 6,
                runSpacing: 4,
                children: [
                  if (r.str('answer_kind') == 'general_ai') const DataKindChip('ai_general'),
                  for (final s in r.objs('sources'))
                    if (s.str('kind') != 'ai_general') DataKindChip(s.str('kind')),
                ],
              ),
            ],
            if (t.pending)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Wrap(
                  spacing: 8,
                  children: [
                    FilledButton.icon(
                      onPressed: _phase == _Phase.thinking ? null : () => _confirm(t),
                      icon: const Icon(Icons.check),
                      label: Text(_kn ? 'ಹೌದು, ಉಳಿಸಿ' : 'Confirm'),
                    ),
                    OutlinedButton(onPressed: () => _cancel(t), child: Text(_kn ? 'ಬೇಡ' : 'Cancel')),
                  ],
                ),
              ),
            if (r != null && t.confirmed)
              Text(_kn ? 'ದೃಢೀಕರಿಸಲಾಗಿದೆ' : 'Confirmed', style: Theme.of(context).textTheme.bodySmall),
            if (t.retry != null)
              TextButton.icon(onPressed: () => _send(t.retry!), icon: const Icon(Icons.refresh), label: const Text('Retry')),
            if (r != null && r.str('disclaimer').isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text(r.str('disclaimer'), style: Theme.of(context).textTheme.bodySmall),
              ),
            if (r != null && t.voice != null) _voiceDetails(context, r, t.voice!),
          ],
        ),
      ),
    );
  }
}
