# Implementation roadmap and checkpoint

Last updated: 2026-10-14, end of the "3-hour product hardening" session. Read this first when resuming. Do not
repeat completed items.

## Verdict: READY FOR INTERNAL TESTING ONLY. Not ready for publication.
* **Evidence for internal testing:** backend and Flutter suites pass (see Tests); farmer–buyer workflows pass
  end to end at API level; the previous build passed on the phone on 2026-10-13.
* **Why not a release candidate:**
  * Today's build has not been used on the phone, and voice with real speech has never been tested on the phone.
  * The publication gates below are open.

## Buyer-demand-first matching and buyer-first top-up (2026-10-15)
Full write-up: `STAGE3_PROGRESS.md` (top section) and `HARVEST_POOL.md` (lifecycle step 5, demand states).
* Demands carry a derived `stage` and live matching (`matched_kg`, `shortage_kg`). Matches and search return
  full/partial/none, shortage, exclusion reasons, explanation and next steps.
* New or newly offered supply tops up open short pools automatically. Farmers still accept.
* Lots show awaiting/confirmed/fulfilled kg. The Flutter buyer and harvest screens use all of it.
* Seven-farmer test: 450 / 500 kg, 50 kg short, both entry points. Backend **1740 passed** (ruff, format and mypy
  clean). Flutter **170 passed**, analyze clean.
* No migration.
* **Deployed 2026-10-15 ~05:52 IST** (one `docker compose up -d --build backend` by harvestique-41, after all four
  sessions said clear).
  * Backup `harvestique_before_voice_pooling_deploy_20261015.dump`: checksum OK; restored into a scratch DB, row
    counts identical to live in all 39 tables.
  * Startup migration was a no-op (still 0015). Live, ready and LAN health checks all returned 200; no errors in
    the logs; row counts unchanged after the deploy.
* **Debug APK** (SHA-256 `481a4a34…`, API `http://192.168.29.100:8000/api/v1`) installed on the SM-M156B. It opens
  and reaches the server (the login screen appears).
* **Seven-farmer scenario over real HTTP** on the isolated manual-test stack (`--profile manualtest`, port 8001,
  same code): **36/36 checks passed**. Covered: buyer-first and farmers-first, the 50 kg shortage, cancellation
  released once, the 8th-farmer top-up, acceptance, duplicate requests and permissions.
* **Not done:** driving the app UI on the phone with two accounts. Script: `STAGE3_PROGRESS.md`.

## Voice and crop-context repair (2026-10-15)
**Root causes (traced live; not the phone's recogniser):**
* "ನಾನು ನನ್ನ ಜಮೀನಿನಲ್ಲಿ ಮಾವು ಬೆಳೆಯುತ್ತಿದ್ದೇನೆ" matched no rule. Kannada gave the fixed "sorry, I did not understand"
  reply, even after a question. English gave generic AI mango tips.
* "What crops are best to grow on my farm?" matched no rule. The model picked `farm_summary`, so the answer only
  counted the farmer's records. The Kannada form hit the same summary.
* There was no statement intent, no recommendation workflow, and no crop carried between turns.
* The app checked only the phone's DEFAULT text-to-speech engine (Samsung's on the test phone) for a Kannada voice.

**Fixed (tests failed before, pass after):**
* Intents `crop_statement` and `crop_recommendation`.
* A statement after a question answers that question. The crop stated earlier is used by later suitability and
  estimate questions.
* Shortlist built from the farmer's own records, the current season and catalogue water needs. No prices or yields.
  It asks for the soil type and water source when they are missing.
* `/voice/intent` returns `normalised`, the text as the server read it.
* App: "Voice details" under each spoken answer. It shows the recogniser's text and locale, its other readings, what
  was sent, what the server read, the intent and the voice engine used.
* App: the voice engine is chosen per language (default engine, then Google TTS, then any other).

**Tests:**
* Backend:
  * `tests/integration/test_assistant_crop_context.py`, 14 tests, through `/assistant/chat` and `/voice/intent`,
    English and Kannada;
  * full suite: 1678 passed. The 1 failure was the layer rule; fixed and re-run.
* Flutter: 152 passed, analyze clean.
* Live trace (current source, live database and services, read-only): `trace_ab_after.json` in the session
  scratchpad.

**Re-check at 05:22 (current tree, which includes other sessions' pooling and crop-health edits):**
* ruff and format clean on the assistant files; mypy clean for the whole app.
* Architecture test plus all assistant tests: 156 passed. Flutter assistant tests: 28 passed.

**Deployed 2026-10-15 05:52:** one rebuild, by session harvestique-41, after all four sessions gave clearance.
* It also shipped harvestique-41's pooling, marketplace and inventory work and harvestique-a8's crop-health work.
* Backup taken first: `harvestique_before_voice_pooling_deploy_20261015.dump` (SHA-256 `729a1450…`). It was
  restore-tested by harvestique-41: row counts identical in all 39 tables.
* Migration step was a no-op: the database stays at `0015`. No errors at startup.
* `/health/live` and `/health/ready` return 200 (database ok, Ollama ok). The API lists 105 paths and
  `AssistantResponse` has `normalised`.
* Live A/B trace inside the deployed container (read-only, rolled back):
  * mango statement → `crop_statement` (EN and KN);
  * best crops → `crop_recommendation` shortlist (EN and KN);
  * the statement after the best-crops question is kept as context;
  * no apology and no prices in any answer.
* Not run: the gemma3:4b evaluation; no AI settings were changed.

**Not verified:**
* Real Kannada speech on the phone (Gate A).
* Google TTS speaking Kannada on the phone (Gate E).
* A local Kannada recogniser (IndicConformer or Whisper) would need a large model download: not done without
  approval.

## Section 12 (2026-10-15): A–Z crop master catalogue and crop-health coverage
Report: `docs/CROP_CATALOGUE_AND_HEALTH_2026-10-15.md`.

**Catalogue:**
* 213 crops (88 kept unchanged + 125 added) in all 18 groups, with scientific names and searchable synonyms (API,
  app and assistant).
* New crops have no Kannada names: not invented.
* Migration 0015 (additive); backup `harvestique_before_0015_20261015.dump` verified.

**Photo check:**
* crop-aware (from the crop cycle or an optional `crop_id`), with part-specific guidance (fruit, tuber, bulb,
  rhizome, flower);
* crop-mismatch flag; new signs: rot, cracking, sunken spots;
* mushrooms get a specialist message.

**Measured (59 leaf photos, blind):**
* crop named correctly 15/56 (27 %);
* plant part "leaf" 59/59 (leaves only; other parts untested);
* health labels unchanged on 54/59 versus earlier runs (3 better, 0 worse).

**Validation status:** `GET /crop-health/validation`. 0 crops reliable; Groundnut not reliable; 212 insufficient
evidence.

**Tests:** backend 1665 passed; Flutter 148 passed. No new APK is required for the server change; a new one
(`02a65504…`) adds alias search in the crop picker.

**Next:**
* a native speaker reviews and adds Kannada names for the 125 new crops (`PATCH /crops/{id}`);
* collect labelled field photos per crop (≥ 30 healthy and 30 problem) before calling any crop reliable;
* test plant-part recognition on fruit, tuber and bulb photos.

## Assistant session 4 (2026-10-14): profit estimates with real mandi prices
Report: `docs/PROFIT_ESTIMATION_2026-10-14.md`.

**Done:**
* AGMARKNET prices via data.gov.in, chosen by district, then state, then neighbouring states; latest day; one
  variety; at most 30 days old; source, market, date and age shown.
* New cache table `market_prices` (migration 0014; backup `harvestique_before_0014_20261014.dump` verified; existing
  data unchanged).
* Costs from the farmer's recorded expenses when not given.
* Actual harvest ("I harvested only 50 kg") vs expected yield; seed, seedling and fertiliser quantities are
  clarified, not used as harvest.
* Break-even price, cautious case, and risks and assumptions in English and Kannada.

**Verified live** with real data.gov.in data, using the public sample key for the test only. Fixed along the way:
* data.gov.in drops Python's default client name;
* a failed refresh was reported as "no price";
* maize prices were mixed across varieties.

**Not found:** a citable government cost-of-cultivation table for tomato in Karnataka, so none was invented.

**Next action (you):**
1. Get a free API key at data.gov.in.
2. Set `MARKET_PRICE_PROVIDER=data_gov_in` and `DATA_GOV_IN_API_KEY` in `.env`.
3. Run `docker compose up -d --build backend`.
Without the key the assistant asks for the price. No new APK is needed.

## Assistant session 3 (2026-10-14): examples, follow-up numbers and estimates
Report: `docs/ASSISTANT_EVAL_2026-10-14.md`, Part 2.

**Defect (phone):** after an income question, "For example 20 kg and ₹50,000" got a generic or invented answer.

**Reproduced live:**
* English: the model invented "₹50,000 to ₹75,000 per acre".
* Kannada: an echo of the numbers.
* Kannada with "ಖರ್ಚು": sent to the past-expenses tool.

**Root causes:**
* estimate replies were not a follow-up topic;
* the estimate read only the current message;
* numbers like 50,000 / 1,20,000 / 50 ಸಾವಿರ / quintal were not read, and numbers with no stated meaning were
  ignored instead of asked about.

**Fix:**
* new `app/domain/assistant/estimate.py` (meaning of each number, units, Indian formats, Kannada; unclear numbers
  are asked about; conversation merge with the newest correction winning; a new crop resets);
* service routing keeps estimate follow-ups in the estimate;
* the calculation is shown step by step from the existing income calculator, with labelled inputs and a
  cautious case;
* the language model is never used for estimates.

**Live after the fix:** the phone example gets a precise clarification in both languages; clarified numbers give
the correct calculation; a price correction changes the result; other topics route normally.

**Tests:** 28 new tests (19 unit, 9 integration). Full backend suite: **1635 passed** (ruff, format and mypy clean). Flutter
148 passed, analyze clean.

**Files:**
* new `backend/app/domain/assistant/estimate.py`;
* `backend/app/services/assistant.py`, `backend/app/domain/assistant/intents.py`, `templates.py`;
* tests: new `tests/unit/test_estimate_parsing.py` and `tests/integration/test_assistant_estimates.py`; updated
  `tests/integration/test_assistant_routing.py`.
* No schema, database or app change. **No new APK is needed.** The server was rebuilt and production AI settings
  are unchanged.

**Phone (not done, needs you):** "ಒಂದು ಎಕರೆ ಟೊಮೆಟೊ ಆದಾಯ ಎಷ್ಟು", then "ಎಕರೆಗೆ 20 ಕ್ವಿಂಟಾಲ್ ಇಳುವರಿ, ಒಟ್ಟು ಖರ್ಚು 50000, ಕೆಜಿಗೆ 25 ರೂಪಾಯಿ".
Check the transcript shows the digits and the calculation is spoken in Kannada.

## Assistant session (2026-10-14, after hardening): general knowledge, tools, English/Kannada parity
Full report: `docs/ASSISTANT_EVAL_2026-10-14.md`.

**Live results** (real model, 12 request types × English and Kannada):
* correct answers 14/26 → **25/26**;
* incorrect or hallucinated answers 6 → **0**;
* routing 21/26 → 26/26.
* The remaining failure is a Kannada follow-up that timed out under load; it answered correctly on 2 of 2 re-runs.

**Root causes fixed:**
* `llama3.2:3b` cannot read Kannada. Kannada general questions are now translated first (with a farming glossary),
  answered in English, and the reply shows "Understood as: …".
* Wrong-language and mixed-script output are rejected.
* Garbled input gets a clarification in the user's language.
* One-acre estimates use the existing income calculator and ask for price and cost (never guessed).
* Crop suitability: farm records + labelled advice + what's missing; no verdict.
* Weather for today/tomorrow states its fetch time and freshness.
* Kannada farm-summary phrasing ("ನನ್ನ ಜಮೀನುಗಳು ಮತ್ತು ಬೆಳೆಗಳು ಯಾವುವು") is recognised.

**Files:**
* backend:
  * `app/domain/assistant/intents.py` (estimate and suitability intents, estimate slots)
  * new `app/domain/assistant/kannada.py`
  * `app/domain/assistant/templates.py`
  * `app/services/assistant.py` (estimate, suitability, weather day, translation, script checks, clarification)
* tests:
  * new `tests/integration/test_assistant_routing.py` (18 tests)
  * updated `test_assistant_conversation.py`, `test_assistant_api.py` (weather call carries `day`),
    `tests/unit/test_assistant_domain.py`, the two voice corpora
* No schema, migration, database or Flutter change.
* **Tests:** backend full suite **1607 passed** (ruff, format and mypy clean); Flutter 148 passed, analyze clean.

**Compatibility:** the APK built earlier (`41e22c35…`) works with this server; **no new APK is needed.**

**Settings:** production AI settings are unchanged (`OLLAMA_MODEL=llama3.2:3b`; Kannada model output stays off).
The server was rebuilt.

**Code backups** of the pre-session versions: the `*.after_voice_fix` files in
`harvestique-backups\code_before_release_hardening_20261014\backend\app\`.

## Done in the hardening session
| # | Issue (evidence) | Root cause | Change | Verified by |
|---|---|---|---|---|
| 1 | Kannada voice answered the wrong thing or didn't understand (reported) | **(a)** Exact-word Kannada patterns missed inflected forms ("ಬೆಳೆಗಳನ್ನು", "ಜಮೀನುಗಳಿವೆ", "ಖರ್ಚಾಗಿದೆ"). **(b)** The kn-IN recogniser writes English words in Kannada script ("ಫಾರ್ಮ್", "ವೆದರ್", "ರಿಮೈಂಡರ್"), and none were matched. **(c)** Zero-width joiners and Kannada digits broke matching. **(d)** Wrong-tool rules: "estimate cost and profit for one acre" went to past expenses; "harvest vs demand" went to the harvest forecast. **(e)** Unmatched Kannada was routed by `llama3.2:3b`, which cannot read Kannada reliably and picked unrelated tools. | Normaliser; Kannada stems and loanwords; comparison and estimate rules; Kannada is **never** routed by the model (own-record question → Kannada "please rephrase" with examples; general question → labelled general answer) | Voice corpus (see Voice results) |
| 2 | First recogniser guess often wrong; 9 other guesses discarded | App sent only the top transcript | App sends up to 5 alternatives; the server tries rules on them **only** when the first is not understood and shows "Understood as: …" | 1 integration test + 1 widget test |
| 3 | Voice navigation ("Open Market", "ಮಾರುಕಟ್ಟೆ ತೆರೆಯಿರಿ", "Go back") not supported | Missing | Allowlisted `navigate` intent (11 keys); server checks the account type; app switches the tab or opens Crop health / Planning / Notifications; unknown keys ignored | integration test (farmer and buyer), 2 widget tests |
| 4 | Kannada spoken on a phone without a Kannada recogniser is silently heard as English | No check | App checks the recogniser's locales and says how to add Kannada | widget test |
| 5 | Buyers could not open the assistant (backend supported them) | No entry button | "Ask" button on the buyer shell | analyzer and widget suite |
| 6 | No cross-role journey test | — | `test_cross_role_journey.py` (2 tests: listing → demand → pool → order → accept → progress → read state → intruders → cancel → demand closed) | passes |
| 7 | Docs | — | this file; `farmer_buyer_interaction_audit.md` | — |

## Voice results (transcript → intent; speech-to-text runs on the phone and is NOT measured here)
| Set | Old rules | New rules | Wrong-tool answers (old → new) |
|---|---|---|---|
| Development corpus, 75 utterances (51 Kannada/mixed, 24 English) | 40/75 (53.3 %); Kannada 27/51 | 75/75 | 16 → 0 |
| Held-out, 38 new phrasings written after the change | 21/38 (55.3 %); Kannada 17/30 | **37/38 (97.4 %)**; Kannada 29/30 | 7 → 0 |

* The development score is optimistic: the rules were written against that corpus.
* The held-out score was measured once. The one miss ("ಖರ್ಚಾಗಿದೆ") was fixed afterwards, so the 97.4 % is the
  pre-fix number.
* Not measured on the phone: recognition accuracy, Kannada TTS intelligibility, latency, background noise.
* Corpus files: `backend/tests/unit/voice_corpus.py`, `voice_corpus_heldout.py`.

## Files changed (backups in `harvestique-backups\code_before_release_hardening_20261014\`)
* **Backend:**
  * `app/domain/assistant/intents.py` (normaliser, stems, navigation)
  * `app/domain/assistant/templates.py` (navigate texts, screen names)
  * `app/services/assistant.py` (alternatives, navigation, no model routing for Kannada)
  * `app/schemas/assistant.py` (`alternatives`, `heard`, `navigate_to`, `understood_by` adds "alternative")
  * `app/api/v1/assistant.py`
* **Backend tests:**
  * new: `tests/unit/test_voice_corpus.py`, `tests/unit/voice_corpus.py`, `tests/unit/voice_corpus_heldout.py`,
    `tests/integration/test_cross_role_journey.py`
  * changed: `tests/integration/test_assistant_conversation.py` (one test changed on purpose: Kannada is no longer
    model-routed; 5 tests added), `tests/unit/test_assistant_domain.py` (sample value `screen`)
* **Flutter:**
  * `lib/features/assistant/voice_engine.dart`, `assistant_screen.dart`
  * new: `lib/features/shell/shell_navigation.dart`
  * `lib/features/shell/farmer_shell.dart`, `lib/features/buyer/buyer_shell.dart`
  * `test/features/assistant/assistant_screen_test.dart` (+5 tests)
* **No migration. No database change.** Generated `docs/API.md` and `docs/DATABASE.md` were checked and are
  unchanged.

## Tests
| | Baseline (start of session) | Final |
|---|---|---|
| Backend (ruff, format, mypy, pytest) | 1502 passed | **1588 passed** (11 min; ruff, format, mypy clean) |
| Flutter (`flutter analyze`, `flutter test`) | 143 passed (2026-10-13 report) | analyze clean; **148 passed** |

## Publication gates (12)
| Gate | Status |
|---|---|
| Backend tests pass | Met |
| Authorization and ownership tested | Met |
| Pooling / inventory deterministic and concurrency-safe | Met (existing suites) |
| Migrations preserve records | Met (no migration this session; 0013 verified on 2026-10-13) |
| Farmer–buyer workflows with separate accounts | Met (API); phone with today's build pending |
| Data persists after restart | Met (database); phone re-run pending |
| **Real-device test of today's build** (voice EN/KN, navigation, buyer Ask button) | **Open** |
| **Release signing** (release builds use debug keys; no `key.properties`) | **Open**: needs your keystore (free, but keep it safe forever) |
| **Application ID** `com.example.harvestique` (Play rejects `com.example`) | **Open**: needs your decision; a new ID installs as a separate app |
| **HTTPS backend reachable from the internet** (the APK targets `http://192.168.29.100:8000`) | **Open**: see costs |
| **Account deletion in the app** (Play policy) and a **privacy policy** (microphone, camera, location, phone number) | **Open**: not implemented |
| **Production settings**: `APP_ENV=development`, `SMS_PROVIDER=dev_console` (development OTP), `CORS_ORIGINS=["*"]` | **Open**: correct for LAN testing only |

## Security findings
* **PostgreSQL is published on all interfaces** (`0.0.0.0:5434`, compose `ports: "${POSTGRES_HOST_PORT}:5432"`), so
  devices on the Wi-Fi can attempt to log in with the default `harvestique` credentials. **Not changed in this
  session**: fixing it recreates the database container. Fix (5 minutes, after a backup):
  1. In `docker-compose.yml`, change the db `ports` to `"127.0.0.1:${POSTGRES_HOST_PORT:-5433}:5432"`.
  2. Run `docker compose up -d db` (the named volume keeps the data).
  3. Verify row counts.
  4. Also change the database password in `.env`.
* Ollama listens on 127.0.0.1 only (good).
* The backend on `0.0.0.0:8000` is intended (the phone needs it); keep it off public networks until HTTPS and
  production settings are in place.
* The authorization matrices and the journey test's intruder checks pass.

## Known limitations
* Order events notify both sides but do not create calendar reminders (workflow #10 partial).
* General (non-record) answers to Kannada questions are in English: the installed models cannot write reliable
  Kannada (measured). The question is translated first and the reading is shown. Record answers are Kannada
  templates; templates and glossary should be reviewed by a native speaker.
* A Kannada general question that needs model translation takes about 30 s on this CPU and can hit the 60 s timeout
  under load (safe failure).
* Crop health: on 20 Koppal groundnut photos, all 10 healthy leaves were called diseased
  (`KOPPAL_GROUNDNUT_EVAL_2026-10-14.md`). The rule stays OFF and the model is unchanged. Results are advisory.
* Voice needs the phone's recogniser (online, or an offline Kannada pack). AI answers need this PC on and reachable.

## Costs (₹0 spent)
Software is free. Real costs if published:
* an always-on host or this PC's electricity;
* a domain (optional; about ₹800–1,000 a year) or a free tunnel subdomain (terms and limits apply);
* the Google Play developer registration ($25 one time);
* SMS for real OTPs (your SIM plan, or a paid gateway).

## Backup, build and deploy status
* **Database backup** before the server update: `harvestique-backups\harvestique_before_voice_deploy_20261014.dump`
  (+ `.sha256`).
  * Read back with `pg_restore --list`: data for all 38 tables.
  * Live state at the time: 14 users, 88 crops, migration `0013_plantation_category`.
  * No database change was made.
* **Code backups:** `harvestique-backups\code_before_release_hardening_20261014\`.
* **Debug APK built, not installed:** `frontend\build\app\outputs\flutter-apk\app-debug.apk` (SHA-256 starts
  `41e22c357f89e87f`), API `http://192.168.29.100:8000/api/v1`.
* **This APK needs the updated server:** it sends `alternatives`, which the old server rejects with 422. Install it
  only after the server rebuild (see Final run).

## Final run
* **Backend suite:** 1588 passed.
* **Flutter:** 148 passed; analyze clean.
* **Server rebuilt** with the new code (`docker compose up -d --build backend`):
  * readiness 200;
  * `/voice/intent` without sign-in → 401;
  * the container has the new schema fields and recognises 'ನನಗೆ ಎಷ್ಟು ಫಾರ್ಮ್ ಇದೆ' → farm_summary,
    'ಮಾರುಕಟ್ಟೆ ತೆರೆಯಿರಿ' → navigate market;
  * database unchanged: 14 users, 88 crops, 0013.

## Exact next actions
1. **You, on the phone (10 minutes):** install the new APK (build command below) and test:
   * English: hold the mic and say "How many farms do I have?", then "Open Market".
   * Kannada: "ನನಗೆ ಎಷ್ಟು ಫಾರ್ಮ್ ಇದೆ", "ನಾಳೆ ಮಳೆ ಬರುತ್ತಾ", "ಮಾರುಕಟ್ಟೆ ತೆರೆಯಿರಿ", "ಹಿಂದೆ ಹೋಗು".
   * Check that the Kannada answer is spoken.
   * Check the buyer "Ask" button.
   * Note what the transcript showed when an answer was wrong.
   * Assistant checks:
     * "ಬೆಳೆ ಸರದಿ ಎಂದರೇನು" → an English answer with "Understood as: What is crop rotation?";
     * "ಒಂದು ಎಕರೆ ಸೌತೆಕಾಯಿ ಖರ್ಚು ಮತ್ತು ಲಾಭ" → asks for price and cost; then
       "ಒಂದು ಎಕರೆ ಸೌತೆಕಾಯಿ, ಕೆಜಿಗೆ 10 ರೂಪಾಯಿ, ಎಕರೆಗೆ 30000 ಖರ್ಚು" → a Kannada estimate;
     * "ನನ್ನ ಜಮೀನಿನಲ್ಲಿ ಕ್ಯಾರೆಟ್ ಬೆಳೆಯಬಹುದೇ" → farm facts + advice.
   * Also: add the soil type and irrigation to your plots so suitability answers have farm data.
2. Bind PostgreSQL to 127.0.0.1 (steps above) when no tests are running.
3. Decide the application ID and create a release keystore; then add account deletion (backend: anonymise the user,
   keep order and ledger rows for the other party; app: Account > Delete account) and a privacy policy page.
4. Optional: create calendar reminders from accepted orders (collection dates).

Build command (debug APK for LAN testing):
`flutter build apk --debug --dart-define=API_BASE_URL=http://192.168.29.100:8000/api/v1` (in `frontend/`).
After changing backend code, rebuild the server: `docker compose up -d --build backend`.
