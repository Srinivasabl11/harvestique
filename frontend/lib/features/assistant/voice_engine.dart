import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:speech_to_text/speech_recognition_error.dart';
import 'package:speech_to_text/speech_to_text.dart';

/// Why listening stopped without words.
enum VoiceProblem {
  /// Nothing was said before the recogniser gave up (silence).
  silence,

  /// Something was heard but not understood.
  noMatch,

  /// The microphone permission was refused.
  permission,

  /// Recognition needs the network (or an offline language pack that is not installed).
  network,

  /// Anything else (audio busy, recogniser crashed...).
  other,
}

VoiceProblem classifyVoiceError(String errorMsg) => switch (errorMsg) {
      'error_speech_timeout' => VoiceProblem.silence,
      'error_no_match' => VoiceProblem.noMatch,
      'error_permission' || 'error_insufficient_permissions' => VoiceProblem.permission,
      'error_network' || 'error_network_timeout' || 'error_server' || 'error_language_unavailable' => VoiceProblem.network,
      _ => VoiceProblem.other,
    };

/// Speech in and out. The app uses the PHONE's own engines (Android speech recognition and text-to-speech): free,
/// no server cost, English (en-IN) and Kannada (kn-IN). Offline use needs the language packs on the phone.
abstract class VoiceEngine {
  /// Prepares recognition; false when the phone has none or the microphone permission was refused.
  Future<bool> init({required void Function(VoiceProblem problem) onError, required void Function() onDone});

  /// [longForm]: press-and-hold dictation. The recogniser may still end a segment after a pause; the screen then
  /// starts a new segment while the button is held and joins the text.
  Future<void> listen({
    required String localeId,
    required void Function(String words, bool isFinal) onResult,
    bool offlineOnly = false,
    bool longForm = false,
    void Function(List<String> alternates)? onAlternates,
  });

  /// Whether the phone's speech recogniser lists a locale for 'en' / 'kn' (false when it cannot tell).
  Future<bool> hasRecognizer(String language);

  bool get isListening;

  Future<void> stopListening();

  Future<void> cancelListening();

  /// Speaks and completes when finished (or when stopped). False when no voice exists for [language].
  Future<bool> speak(String text, String language);

  Future<void> stopSpeaking();

  /// Whether a text-to-speech voice for 'en' / 'kn' is installed.
  Future<bool> hasVoice(String language);

  /// The text-to-speech engine last chosen for speaking (e.g. com.google.android.tts), null when not known.
  String? get ttsEngine;
}

class DeviceVoiceEngine implements VoiceEngine {
  final _stt = SpeechToText();
  final _tts = FlutterTts();
  void Function(VoiceProblem)? _onError;
  void Function()? _onDone;
  bool _ttsReady = false;
  String? _engine; // the engine currently bound
  final _engineFor = <String, String?>{}; // language -> engine with a voice for it (null: none)

  @override
  String? get ttsEngine => _engine;

  static String ttsLocale(String language) => language == 'kn' ? 'kn-IN' : 'en-IN';

  @override
  Future<bool> init({required void Function(VoiceProblem problem) onError, required void Function() onDone}) async {
    _onError = onError;
    _onDone = onDone;
    try {
      return await _stt.initialize(
        onError: (SpeechRecognitionError e) => _onError?.call(classifyVoiceError(e.errorMsg)),
        onStatus: (s) {
          if (s == 'done' || s == 'notListening') _onDone?.call();
        },
      );
    } catch (_) {
      return false;
    }
  }

  @override
  Future<bool> hasRecognizer(String language) async {
    try {
      final locales = await _stt.locales();
      if (locales.isEmpty) return true; // some recognisers do not report their languages: do not block
      return locales.any((l) => l.localeId.toLowerCase().replaceAll('-', '_').startsWith('${language}_'));
    } catch (_) {
      return true;
    }
  }

  @override
  bool get isListening => _stt.isListening;

  @override
  Future<void> listen({
    required String localeId,
    required void Function(String words, bool isFinal) onResult,
    bool offlineOnly = false,
    bool longForm = false,
    void Function(List<String> alternates)? onAlternates,
  }) =>
      _stt.listen(
        onResult: (r) {
          if (r.finalResult && onAlternates != null) {
            // the recogniser's other readings of the same speech (it is asked for up to 10); the server tries them
            // only when the first one is not understood
            onAlternates(
              r.alternates
                  .map((a) => a.recognizedWords.trim())
                  .where((w) => w.isNotEmpty && w != r.recognizedWords.trim())
                  .toSet()
                  .take(5)
                  .toList(),
            );
          }
          onResult(r.recognizedWords, r.finalResult);
        },
        listenOptions: SpeechListenOptions(
          localeId: localeId,
          listenFor: Duration(seconds: longForm ? 120 : 20),
          // tap mode: a 3 s pause ends the question; hold mode: the button decides (segments are joined)
          pauseFor: Duration(seconds: longForm ? 10 : 3),
          partialResults: true,
          cancelOnError: true,
          onDevice: offlineOnly,
          listenMode: ListenMode.confirmation,
        ),
      );

  @override
  Future<void> stopListening() => _stt.stop();

  @override
  Future<void> cancelListening() => _stt.cancel();

  @override
  Future<bool> speak(String text, String language) async {
    try {
      if (!_ttsReady) {
        await _tts.awaitSpeakCompletion(true);
        _ttsReady = true;
      }
      if (!await hasVoice(language)) return false;
      await _use(_engineFor[language]);
      await _tts.setLanguage(ttsLocale(language));
      await _tts.setSpeechRate(0.45);
      await _tts.speak(text);
      return true;
    } catch (_) {
      return false;
    }
  }

  @override
  Future<void> stopSpeaking() async {
    try {
      await _tts.stop();
    } catch (_) {
      // nothing is playing
    }
  }

  @override
  Future<bool> hasVoice(String language) async {
    if (!_engineFor.containsKey(language)) {
      try {
        final engines = ((await _tts.getEngines) as List<dynamic>? ?? const []).map((e) => '$e').toList();
        final engine = await pickTtsEngine(
          defaultEngine: (await _tts.getDefaultEngine) as String?,
          engines: engines,
          hasLanguage: (engine) async {
            await _use(engine);
            return await _tts.isLanguageAvailable(ttsLocale(language)) == true;
          },
        );
        _engineFor[language] = engine;
      } catch (_) {
        // engines cannot be listed (not Android): ask the current engine only
        try {
          return await _tts.isLanguageAvailable(ttsLocale(language)) == true;
        } catch (_) {
          return false;
        }
      }
    }
    return _engineFor[language] != null;
  }

  Future<void> _use(String? engine) async {
    if (engine == null || engine == _engine) return;
    await _tts.setEngine(engine);
    // Android binds the new engine asynchronously; asking it at once may still reach the old one
    await Future<void>.delayed(const Duration(milliseconds: 400));
    _engine = engine;
  }
}

final voiceEngineProvider = Provider<VoiceEngine>((ref) => DeviceVoiceEngine());

const googleTts = 'com.google.android.tts';

/// The phone's DEFAULT text-to-speech engine may have no Kannada voice (Samsung phones default to Samsung's engine)
/// while Google's engine, also installed, does. Checks the default first, then Google's, then any other engine, and
/// returns the first one with a voice for the language (null: none has).
Future<String?> pickTtsEngine({
  required String? defaultEngine,
  required List<String> engines,
  required Future<bool> Function(String engine) hasLanguage,
}) async {
  final order = <String>{
    if (defaultEngine != null && defaultEngine.isNotEmpty) defaultEngine,
    if (engines.contains(googleTts)) googleTts,
    ...engines,
  };
  for (final engine in order) {
    if (await hasLanguage(engine)) return engine;
  }
  return null;
}
