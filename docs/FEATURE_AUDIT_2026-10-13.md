# Feature status audit (2026-10-13)

Evidence levels: **A** = automated tests (backend pytest / Flutter widget tests), **API** = direct calls against the
live server, **Phone** = used on the real Android phone (seen in the live database or tested on screen).
"Completed" needs all three; anything without phone evidence is at most "Partially completed".

State at audit time: no code changes since 2026-10-10; live DB at migration `0012_crop_categories`, 13 users, 80
crops; last APK installed 2026-10-10 04:30. Phone connected but adb reports **unauthorized** (USB-debugging permission
must be accepted on the phone again after the PC restarted), so no on-screen testing was possible today.

Phone evidence found in the database: the guided tour was recorded on 4 real accounts (farmer "vasa", buyer
"Srinivasa bl", "farmer", "buyer"); two crop-health photos were analysed on 2026-10-12 (both "unknown").

| # | Feature | Status | Evidence | Remaining work | Test required |
|---|---|---|---|---|---|
| 1 | Forgot password | Partially completed | A: `test_password_reset.py`, `forgot_password_test.dart`; API: reset, old session revoked, unknown number same response. HMAC codes, 5 min expiry, 60 s resend cooldown, 5 sends/phone/h, 20/device/h, 5 attempts; new-password rules; dev code shown only with `SMS_PROVIDER=dev_console`, refused in production | Real SMS needs a provider (cost) | Phone: Forgot password from the login screen, farmer and customer |
| 2 | Voice assistant (press-and-hold, long speech, partial results, cancel, text fallback) | Partially completed | A: 19 widget tests (`assistant_screen.dart`, `voice_engine.dart`); text input kept | Real microphone behaviour, Kannada recognition on the device | Phone: hold mic, speak a long sentence, slide to cancel |
| 3 | General + personal AI assistant | Partially completed | A: routing/scope/filter tests; API: general (`general_ai`) and mixed answers via Ollama `llama3.2:3b`; `farm_summary` tool added; personal-claim and "can't see your records" sentences removed | Kannada general answers are off (small local models wrote poor Kannada); Kannada record questions work | Phone: one personal, one general, one mixed question (EN + KN) |
| 4 | Notifications (mark as read, unread count, refresh) | Partially completed | A: `notifications_reminders_test.dart`, backend engagement tests | No read since 2026-10-10 in the DB, so not exercised on the new build | Phone: open bell, mark one read, badge drops; mark all read |
| 5 | Edit / delete with ownership and history | Partially completed | A + API: farms (archive), plots, crops (abandon), observations, expenses, reminders, plans and plan items, harvest correction (audited), admin batch removal; ownership matrices (`test_phase6_authorization.py`, `test_intelligence_authorization.py`) | **Gaps:** buyer demands cannot be cancelled (status exists, no endpoint/UI); farm activities have backend edit/delete but **no app screen at all** | A + Phone |
| 6 | Reminders | Partially completed | A: past-time refusal, edit/reschedule/delete, single submit; API: create/edit/delete, past refused | Phone run | Phone: create, edit time, complete, delete |
| 7 | Guided tours | **Completed** | A: `tour_help_test.dart`; Phone: tour recorded on 4 real accounts (farmer and buyer) | Replay from Help & guide not yet seen on phone | Phone: Account > Help & guide > Start the guided tour |
| 8 | Order notifications | Partially completed | A: order placed -> farmer request notification (order ref, crop, kg); accept/decline/preparing/ready -> buyer, deduplicated; unread counts from the same table | Not run live: a live run would send requests to your real farmer accounts' lots, so it needs your two real accounts on the phone. No SMS/push (in-app only) | Phone: buyer orders, farmer accepts, marks ready, buyer sees notification |
| 9 | Farm weather | Partially completed | A: `weather_card_test.dart`, `test_weather_now.py`; API: Open-Meteo current conditions, 12 h rain probability, timestamp | Phone run | Phone: Home weather card, farm picker, Refresh |
| 10 | Crop-health analysis | Partially completed | A: `test_vision_ollama.py` (25+); API: 3 real photos; Phone: 2 real uploads 2026-10-12 reached the vision model (pipeline works) but both came back "unknown": the model's own "not close-up" / "poor photo" judgement discarded what it saw ("markings", "yellowing and browning") and the advice was generic | **Fix:** keep visible symptoms with low confidence when the model only doubts photo quality; give specific retake guidance per problem; read "browning" | A + Phone with your own leaf photos |
| 11 | Crop catalogue | Partially completed | 80 crops, no duplicate names or Kannada names; fodder and medicinal categories | **Gaps:** no plantation category (coconut, arecanut, coffee are "cash crop"; no tea, rubber, cashew); minor millets missing (little, kodo, proso, barnyard) | A + migration on a backup |
| 12 | Market and Harvest | Partially completed | A: marketplace/pooling/inventory suites; Harvest lot names, single-submit controls; buyer search/demand validation | Demand cancel (see 5); full lifecycle on the phone with real buyer + farmer accounts | Phone (see 8) |
| 13 | User experience | Partially completed | Tooltips on all icon buttons, spinner labels, snackbar replacement, manual | Farm activity log missing from the app; phone review of screens | Phone |
| 14 | Free operation | **Completed** | Ollama (local), device speech, Open-Meteo, in-app notifications; no paid API in config | Real SMS and any hosting would cost money (disclosed) | — |

## Priority of remaining work
1. Crop health: real phone photos come back "unknown" (observed bug).
2. Catalogue: plantation category and minor millets (migration 0013, backup first).
3. Buyer demand cancellation (endpoint + button).
4. Farm activity log screen (list / add / edit / delete) for the existing backend.
5. Phone verification of 1-12 once USB debugging is re-authorised (or by you, with the steps in the report).

## Stage results (2026-10-13, same session)
Backup before migration 0013: `harvestique_before_0013_20261013_2257.dump` (+ `.sha256`), restored into a scratch DB,
identical row counts in 38 tables. After deploying, only `crops` changed (80 -> 88).

| Stage | Change | Evidence |
|---|---|---|
| 1 Crop health | A doubtful photo ("not close-up", "poor photo") keeps visible signs at **low** confidence with a specific retake tip instead of a blanket "unknown"; "healthy"/"unclear" while describing signs goes by the signs (same definitions as the prompt); "browning" recognised; app title says "Uncertain:" / "Unclear from this photo" | A: 36 vision unit tests incl. both 2026-10-12 phone descriptions as regressions; real-photo re-run (8 public photos): 4/4 spotted or deficient leaves -> possible disease (deficiency category still wrong), healthy tomato -> healthy, field photo -> unclear; **new false alarm**: healthy brinjal (poor photo) -> "Uncertain: Stress" |
| 2 Catalogue | Migration `0013_plantation_category`: plantation category; Coconut, Arecanut, Coffee moved (ids kept); Tea, Rubber, Cashew; Little, Kodo, Proso, Barnyard, Browntop millets; app shows "Cereals & millets", "Plantation crops" | A: crop tests; API: 6 plantation crops live; 88 crops, no duplicate names |
| 3 Buyer demands | `POST /buyer-demands/{id}/cancel` (only before pooling; pooled -> 409 "cancel its order instead"; repeat harmless; owner-only via the authorization matrix); demand list/detail show the crop name; "Withdraw this demand" with confirmation | A: pooling API + authorization tests, widget test. Not run live (a live demand would notify your real farmer accounts) |
| 4 Field work log | New `activities_screen.dart` (list, add, edit, delete with confirmation, single submit, no future dates) linked from the farm page and the crop page; manual updated | A: 3 widget tests; API: create/edit/delete, future date refused (422) on the test farmer's test farm |

Tests: backend 1478 passed (full run), ruff/format/mypy clean; Flutter 138 passed, `flutter analyze` clean.
APK built (sha256 e0837d1c…c2b7) but **not installed**: phone still "unauthorized" for USB debugging.
