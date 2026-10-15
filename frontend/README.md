# Harvestique - Flutter app (Android)

The app talks to the real FastAPI backend; there is no fake or disconnected data in it.

## First build (needs the Flutter SDK and Android SDK)

```powershell
cd frontend
flutter create . --platforms=android --org com.example --project-name harvestique   # already done
flutter pub get
flutter analyze
flutter test
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000/api/v1          # emulator
flutter build apk --debug --dart-define=API_BASE_URL=http://192.168.29.200:8000/api/v1   # phone on the same Wi-Fi
flutter build apk --dart-define=API_BASE_URL=https://<your-server>/api/v1
# shareable release APK for the hosted server: scriptsuild-release-apk.ps1 (docs/DEPLOYMENT.md)
```

`flutter create .` does not overwrite existing files, so `lib/`, `test/`, `pubspec.yaml` and both
`AndroidManifest.xml` files (main: microphone permission and speech/TTS queries; debug: cleartext HTTP to the local
dev backend) are kept. Delete the generated `test/widget_test.dart` (it references a counter app).

**Status (2026-10-10):** `flutter analyze` reports no issues and `flutter test` passes (92 tests). The Android
project files were restored with `flutter create . --platforms=android --org com.example --project-name harvestique`
(application ID `com.example.harvestique`, the ID of the build already on the test phone, so new builds install as an
update). A debug APK builds and starts on a Samsung Galaxy M15 (Android 16) and reaches the backend.

## "Build failed due to use of deprecated Android v1 embedding"

Run from the repository root (needs only Python 3.10+):

```powershell
python scripts\migrate_android_embedding.py            # shows what makes Flutter see V1, changes nothing
python scripts\migrate_android_embedding.py --apply    # backs up android\ to frontend\.android_backup_<time>\ and fixes it
flutter clean; flutter pub get; flutter build apk
```

It fixes only V1 leftovers (manifest `flutterEmbedding`/`FlutterApplication`, a V1 `MainActivity`, a committed V1
`GeneratedPluginRegistrant.java`) and never changes the application ID, permissions, Gradle plugins or dependencies.

## What is in the app

| Role | Tabs / screens |
|---|---|
| Farmer | Home (weather, risk, requests, reminders) · My Farm (farms, plots, crops, predictions with confidence/risk/sources, observations, crop-health photos, harvest recording, prediction feedback, expenses, income plans: create → add crops by hand or from a prediction → estimated net income next to actual recorded expenses) · Market (buyer demand, supply requests: accept/decline) · Harvest (virtual inventory, offer to buyers, expected grade, deliveries) · Reminders (suggestions, calendar) · Ask Harvestique (voice-first assistant, English/Kannada) |
| Buyer | Market (future supply, harvest search) · Demands (ranked matches, harvest pool, reallocation events, audit ledger, place order) · Orders (status, cancel, traceability) · Reminders |
| Admin | Dashboard · Orders (receive batches, quality checks, fulfilment) · Quality queue · Collection hubs |

Fixed UI labels are English; assistant and voice replies follow the chosen language (English or Kannada).

## Sign-up and sign-in (phone verification)
Both are two steps: details (or phone + password), then the one-time code sent by SMS (`/verify` screen: 6-digit
code, resend after a countdown, attempts left). The app stores tokens only after the server accepts the code. On a
development server without an SMS provider the code is shown in a box marked "DEVELOPMENT MODE – not sent by SMS".
Phone numbers are entered with a country code (+91 by default).

**An older build of the app cannot sign in to this backend** (it expects tokens straight from `/auth/login`). Install
a build of this version. Sessions already open on the phone keep working until they expire (refresh tokens last
14 days).

## Ask Harvestique (assistant)
* A large microphone button that speaks and listens in English (en-IN) or Kannada (kn-IN) using the phone's own,
  free speech engines. Typing always works.
* Conversation mode (menu): after each answer it listens again while the screen is open. Say "stop" / "ಸಾಕು" to
  end. There is no background wake word.
* Tap the microphone to interrupt a spoken answer or cancel a question in progress.
* Saving something (an expense, a reminder) needs a spoken "yes" / "ಹೌದು" or the Confirm button.
* Follow-up questions ("and tomorrow?", "what about ragi?") use the conversation so far.
* Kannada speech needs the phone's Kannada speech-recognition and text-to-speech packs (Settings → Languages /
  Text-to-speech). The screen says when one is missing.
Speech recognition and speech output run on the phone (`speech_to_text`, `flutter_tts`, locales en-IN / kn-IN);
Kannada needs the Google speech and TTS language packs installed on the device.

## Behaviour in poor connectivity

* Main lists and screens save their last successful response (`shared_preferences`) and show it with an
  "Offline: showing data saved on ..." banner when the server cannot be reached. Server errors are never hidden.
* Writes (accept, decline, reminders, quality) are not queued offline: they fail with a clear message.
* Notifications are an in-app feed polled every minute while the app is open. Android system-tray notifications are
  not wired yet (no push service is used).

Structure: feature-first (`lib/features/<feature>/`), shared code in `lib/core/` (API client with token refresh,
secure token storage, offline cache, JSON readers, shared widgets for loading/error/empty/offline, confidence, risk
and data-provenance indicators).
