# Stage 3 work log (feature fixes and UX pass, requested 2026-10-10)

Kept up to date during the work so an interrupted session can resume. Newest state first.

## Buyer-demand-first matching, shortages and reallocation (2026-10-15, two sessions)
Split agreed between two Claude sessions: **harvestique-41 = backend** (services/pooling.py, marketplace.py,
inventory.py, schemas, domain/pooling, repositories, backend tests, HARVEST_POOL.md/API.md), **harvestique-34 =
Flutter** (frontend/ only, plus this section). The repository is not under Git; backups of the Flutter files changed
here are in that session's scratchpad (`backup_flutter_0514`).

**Already existed (reused, not duplicated):** buyer demands, crop-filtered matching with exclusion reasons, p10-based
reservations through the inventory, greedy/LP pools, newest-first shortage cutting, reallocation events and an
append-only ledger, orders with farmer accept/decline, hubs, batches, quality, fulfilment, notifications.
**Found unfinished:** `summarize()`, `demand_stage()` and `short_pools_for_crop()` were written but never called,
so the API's `fulfilment`/`explanation`/`next_steps`/`stage` fields were always defaults, and `LotOut`'s
awaiting/confirmed/fulfilled split was never filled.

### Flutter (harvestique-34): done, verified
| Change | File |
|---|---|
| Shared buyer words: demand stages (incl. `matching_supply_available`), exclusion reasons, next steps; full/partial/none and shortage worked out from the numbers when an older server omits them | `lib/features/buyer/supply_status.dart` (new) |
| Demand list: stage chip and "Short by" per demand | `demands_screen.dart` |
| Demand detail: live stage card (re-fetched, not the stale list copy); supply summary card (needed, eligible p10 supply, shortage, server explanation, excluded lots by reason, next steps); "Create pool" hidden when nothing is eligible, labelled "Create pool for the available N kg" when partial | `demands_screen.dart` |
| New demand: optional "Deliver near" collection hub (hubs with coordinates) + maximum distance (validated, 0 < km <= 2,000), sent as the existing latitude/longitude/max_distance_km fields | `demands_screen.dart` |
| Search: same summary card; states that a search reserves nothing | `search_screen.dart` |
| Farmer Harvest card: predicted (p50, estimate) vs weighed harvest (measured) vs can promise vs committed, and the awaiting/confirmed/delivered split when the server sends it; prompt to update the prediction | `harvest/harvest_screen.dart` |
| Tests: 14 new (seven-farmer 450/500/50 kg screen, no supply, full supply + idempotent pool, older server, supply-changed stage with an existing pool, list stages, arithmetic/word maps, distance validation, harvest quantity split) | `test/features/buyer/demand_matching_test.dart` (new), `test/features/harvest/harvest_screen_test.dart` |

Results (run 2026-10-15 ~05:25 on this PC, Flutter SDK `C:\src\flutter`): `flutter analyze` **no issues**;
`flutter test` **170 passed** (baseline before the change: 156 passed).

Incident: `dart format` was run once on the whole `buyer/` folder by mistake. `pool_screen.dart` and
`search_screen.dart` were restored to their original text; `trace_screen.dart`, `order_detail_screen.dart` and
`buyer_home_screen.dart` kept whitespace-only line-break changes (no backup existed; behaviour unchanged; the two
lint warnings it caused were fixed).

### Backend (harvestique-41): done, verified
| Change | File |
|---|---|
| `GET /buyer-demands/{id}/matches` and `GET /market/harvests` return `fulfilment`, `shortage_kg`, `excluded_reasons`, `explanation`, `next_steps` (from the existing `summarize()`); fixed the duplicate `eligible_count` field that broke mypy | `services/pooling.py`, `schemas/pooling.py` |
| Every demand response carries `stage` (from `demand_stage()`), `pool_id`, `order_id`, `allocated_kg`, `remaining_kg`; open demands are re-matched live (`matched_kg`, `shortage_kg`; stage `matching_supply_available` / `partially_matched` / `no_matching_supply`, nothing reserved) | `services/pooling.py`, `domain/pooling/shortage.py` |
| **Buyer-first top-up:** a newly offered, regraded, new or higher-predicted lot tops up open short pools of the same crop it is eligible for, oldest first (trigger `supply_added`, own transaction, idempotent key, audited, uses `short_pools_for_crop()`). Pools it does not fit get no event. The farmer still accepts or declines | `services/pooling.py` |
| Buyer notification "New supply found for your demand" for top-ups (it used to read "Shortage 0 kg, replaced 0 kg") | `services/marketplace.py` |
| Lots return `awaiting_confirmation_kg`, `confirmed_kg`, `fulfilled_kg` (from order items), including the opt-in PATCH response | `services/inventory.py`, `repositories/intelligence.py` |
| Tests: new `tests/integration/test_seven_farmer_scenario.py` (10 tests); `demand_stage` unit cases; manual tomato scenario updated (t4's offer now tops up automatically and the buyer's "Check for new supply" is `no_change`) | tests |

No migration, no schema/database change (`DATABASE.md` and `API.md` regenerate unchanged).

**Seven-farmer test** (separate accounts, real API, PostgreSQL, `demo_scripted` predictor echoing each farmer's
estimate): `test_a_farmers_first_then_buyer_450_of_500_kg_with_a_50_kg_shortage` passes: eligible 450 kg (A 150,
B 200, F 100), shortage 50 kg, `partial`, onion/potato/chilli/cabbage never listed or reserved, order stays `placed`
with 50 kg uncovered after all three accept; an onion farmer does not change it; an 8th tomato farmer with 60 kg is
proposed exactly 50 kg (keeps 10) and, after accepting, the order is `confirmed` at 500 kg.
`test_b_buyer_first_then_farmers_reaches_the_same_state` passes with the same A/B/F split (three `supply_added`
top-ups). Also passing: live re-matching as each of the seven registers, grade/date/distance/opt-in exclusions
with reasons, unsuitable supply never tops up, prediction drop 150 -> 80 (exact 70 kg shortage, history kept,
others' accepted quantities untouched, replaced by a 70 kg farmer pending acceptance), cancel releases exactly once,
repeated opt-in/pool requests never double-allocate, two concurrent buyers (300 + 300 kg against 450 kg) get
300 + 150, ownership checks (404/403).

**Results** (2026-10-15, own test database `harvestique_test_41`): ruff **clean**, ruff format **clean**, mypy
**clean**, full pytest **1740 passed, 0 failed** (24 min, three suites sharing the PC); afterwards
`tests/unit/test_pooling_domain.py` with the new `demand_stage` cases: **49 passed**.

**Independent re-check** by harvestique-34 (2026-10-15, separate test database `harvestique_test_34`, read-only
source mount, `hq-test-runner` image): ruff, ruff format and mypy (173 files) **clean**; targeted pytest
(seven-farmer, pooling, marketplace, cross-role journey, manual tomato, inventory, pooling + phase-6 authorization,
pooling domain, architecture, docs-in-sync) **162 passed, 0 failed** (4 min 47 s).

### Deployment and live verification (harvestique-41, 2026-10-15 05:50-06:05 IST)
| Step | Result |
|---|---|
| Other sessions | a8 (crop health), 5f (assistant) and 34 (Flutter) all said "clear"; harvestique-41 was the only builder. No evaluation running at the start. |
| Backup | `harvestique-backups\harvestique_before_voice_pooling_deploy_20261015.dump` (05:49): SHA-256 matches; restored into a scratch DB; row counts **identical to live in all 39 tables** (14 users, 213 crops, 3 demands, 1 order); scratch DB dropped |
| Deploy | one `docker compose up -d --build backend`; image `dc83436ac949…`; alembic no-op (0015); container healthy |
| Health | `/health/live` 200, `/health/ready` 200 (database ok, llm:ollama ok), LAN `192.168.29.100:8000` 200; unauthenticated `/buyer-demands` 401; no errors in startup logs; new pooling code present in the container |
| Data | row counts after the deploy identical in all 39 tables |
| APK | `flutter build apk --debug --dart-define=API_BASE_URL=http://192.168.29.100:8000/api/v1`; SHA-256 `481a4a343b700c40…`; `adb install -r` Success on SM-M156B (v0.6.0, 05:55); app opens, live server receives its requests (`/auth/me` 401 = sign in again), login screen shown |
| Seven-farmer scenario, real HTTP | **36/36 passed** against the isolated manual-test stack (`docker compose --profile manualtest`, port 8001, own DB container and volume, same code, `demo_scripted` predictor). Separate buyer and farmer accounts. Buyer first: an empty pool fills to 450 kg on its own (A150/B200/F100), 50 kg unfilled, "New supply found" notice. A repeated order key returns the same order. Cancel: 200, a second cancel 409, A's 150 kg free again, stage cancelled. Farmers first: partially_matched 450/50, only tomato listed, explanation and next steps shown, a repeated pool request returns the same pool, all three accept, order stays placed with 50 kg uncovered. An onion grower changes nothing. An 8th farmer with 60 kg is asked for exactly 50 (keeps 10, 50 awaiting); they accept, a repeated accept gets 409, order confirmed at 500. Repeated opt-in: no double allocation. Permissions: another buyer 404 on demand and cancel; farmer 403 on demand create and order cancel; another farmer 404 on lot PATCH and on accept. No farmer phone or name in matches. Script: session scratchpad `live_seven.py`. |
| Crop health / assistant | Live: routes present (`/crop-health/validation`, `/assistant/chat` and `/voice/intent` all 401 without sign-in). Two real photo checks from the owner's phone (`POST /crop-health/analyze`, Kannada) returned 200 on live at 05:56 and 06:00 IST, one gemma3:4b call each. This confirms the deployed crop-health path works. **No evaluation was started**: no eval container and no result files (checked by harvestique-a8). Isolated stack (no model): validation report 200; Kannada mango statement → `crop_statement` (Kannada reply); "best crops" → `crop_recommendation` (asks for farm details); "Open Market" → `navigate: market`. harvestique-5f's live trace (EN/KN, `normalised` present) passed. |

**Not tested:** driving the app screens on the phone with the two accounts. I did not sign in on the phone: the
login form held the owner's real account, and test accounts were not created in live data. Manual steps for the
owner:
1. Start the isolated test server: `docker compose --profile manualtest up -d db-manualtest backend-manualtest`
   (already running).
2. Build an APK that points at it: `flutter build apk --debug
   --dart-define=API_BASE_URL=http://192.168.29.100:8001/api/v1`. Or use the live APK with real accounts.
3. With one buyer and two or more farmer accounts, repeat the 500 kg tomato steps above on the screens.

Clean-up of the isolated test data (it never touches live data):
`docker compose --profile manualtest down -v`.

### Remaining / not done
* No maximum-price constraint: Harvestique stores no prices by design (HARVEST_POOL.md "Limits"); adding one needs a
  product decision and a migration.
* The live backend is deployed and the APK is installed (see above). Still open: the two-account test driven
  through the phone screens.
* The API has kilograms only (no unit conversion). Opting a lot out does not withdraw requests it already has.

## Safety
* Verified database backups (restored into a scratch DB, identical row counts in all tables):
  `C:\Users\Srinivasa\Documents\harvestique-backups\harvestique_before_stage3_20261010_0209.dump` (+ `.sha256`).
* Second verified backup before applying 0009-0012: `harvestique_before_0009_0012_20261010_0405.dump` (+ `.sha256`),
  restored into a scratch DB: identical row counts in all 38 tables.
* Live DB is now at `0012_crop_categories` (applied 2026-10-10 04:2x by rebuilding the backend container). After
  deploying, only `crops` changed (19 -> 80, the 19 originals untouched); every other table has the same row count.

## Status by item (requested numbering)
| # | Item | Status |
|---|---|---|
| 1 | Forgot password | **done**: backend + tests (`test_password_reset.py`, migration 0009), Flutter `forgot_password_screen.dart` + `test/features/auth/forgot_password_test.dart` |
| 2 | Push-to-talk voice | **done**: press-and-hold, segment joining, slide-to-cancel, tap hints (`assistant_screen.dart`, `voice_engine.dart`; 19 widget tests); message limit 500 -> 1000 |
| 3 | Assistant general/mixed routing | **done** (automated tests): `question_scope`, general answers allow numbers (marked approximate), personal-claim sentences removed, mixed answers, Kannada -> English answer with Kannada note; live Ollama check pending |
| 4 | Notifications + reminders | **done**: per-item Mark as read (optimistic + rollback + Retry), badge refresh, Mark all read feedback; reminders edit/reschedule/delete (+ `DELETE /reminders/{id}`), past-time validation, single-submit; tests (backend engagement, `test/features/notifications_reminders_test.dart`) |
| 5 | Edit/delete | **done**: farms (edit incl. coordinates / archive / restore / delete-or-archive, archived toggle), plots (edit / delete-or-archive), crops (edit / mark abandoned / delete-or-abandon), observations (full form, edit, delete), expenses (edit), plan entries (earlier), reminders (item 4), harvest correction (`PATCH /crop-cycles/{id}/harvest-actual`, only before a hub batch; audit columns, migration 0011), admin batch removal before quality check (`DELETE /admin/batches/{id}`); shared `record_actions.dart`, `edit_dialogs.dart`; tests |
| 6 | Guided tour | **done**: role-specific versioned tour (`onboarding/tour.dart`, `kTourVersion`), shown once per account after sign-in, Skip/Back/Next/Finish, restart from Account > Help & guide; tests |
| 7 | Order lifecycle notifications | **done**: `POST /participations/{id}/progress` (preparing -> ready, forward only, deduplicated buyer notification), decline notifies buyer, order ref/crop/quantity in all participation notifications, `farmer_progress` on order items, Flutter accepted-orders card + order IDs (migration 0010) |
| 8 | Weather card | **done**: `GET /farms/{id}/weather/now` (Open-Meteo current + 12 h + 7 days, 15 min cache, stale fallback <= 6 h, labelled model estimates), Home `FarmWeatherCard` (farm picker, raining-now chip, rain chance, retry, location guidance); tests |
| 9 | Crop health | **done** (automated + real public photos through the live local model): `providers/vision/ollama.py` (`CROP_HEALTH_CLASSIFIER=ollama_vision`, `gemma3:4b`, about 3.3 GB disk, about 6 GB RAM, 60-75 s per photo on this i7-7700 CPU), structured JSON answer validated (description first, close-up check, symptom cross-check from the description, contradictions -> unclear, treatment/dose sentences removed, probabilities capped at 0.70); colour heuristic now measurements only (its labels were wrong on 7 of 8 real photos) and the fallback when the model is missing/slow; exposure normalisation for dim photos; analysis runs off the event loop; Flutter: 180 s timeout, progress text, symptoms, colour-only view; tests |
| 10 | Crop catalogue | **done**: categories `fodder`, `medicinal` (migration 0012), 61 more crops (80 total) added by name only, existing ids/edits untouched; Kannada names only where well established (2 left blank); durations labelled indicative, perennials use a 365-day record-keeping cycle; no invented yields; Flutter category chips + search, all pages loaded (`getAll`); tests |
| 11 | Market/Harvest audit | **done** (automated + direct API): lots carry crop/plot/farm/sowing date (Harvest showed only "Lot · Open"); offer-to-buyers switch and grade picker single-submit with Saving…, reload only on success; deliveries and earlier requests show order numbers and progress; buyer search and New demand explain missing crop/quantity instead of silently doing nothing, show crop-loading errors, and cannot double-submit (duplicate demands); decline reason limited to the server's 255 characters; all crop pickers load every page |
| 12 | Usability | **done** (scoped): every icon button already had a tooltip; all loading spinners now have a screen-reader label; action messages replace the previous one instead of queueing; manual updated (crop picker, AI photo check); assistant gained a read-only `farm_summary` tool ("how many farms do I have") and drops "I cannot see your records" sentences from general answers |
| — | In-app user manual | **done**: `help/help_screen.dart` (searchable, role-specific), Account > Help & guide |

## Audit findings (root causes)
* Notifications "Mark as read": backend correct (DB rows show read_at set). App: no per-item control (whole row tap
  only), no success feedback, unread badge refreshed only after leaving the screen, unread vs read differs only by
  bold text. Server log: "Mark all read" pressed 10 times in a row.
* Reminders: no edit/delete/reschedule UI (backend has PATCH, complete, dismiss; no DELETE); Save can be double
  tapped (duplicates); empty title silently ignored; complete/dismiss give no feedback.
* Orders: placed -> farmer participation request, farmer accept/decline -> buyer, collection/quality/fulfilment
  notifications already exist (deduplicated). Missing: farmer "preparing"/"ready" steps with buyer notification.
* Weather: Open-Meteo adapter fetches daily aggregates only; no current conditions, no rain probability.
* Crop health: all 6 real uploads returned "unknown". The colour heuristic's gates (plant fraction >= 45 %, green
  share, sharpness) reject real photos (e.g. a 99.9 % green but slightly dark photo measured 8 % plant). Needs a
  local vision model; hardware/licence to be stated before download.
* Catalogue: 19 crops, categories lack fodder and medicinal/aromatic.

## Migrations
* `0009_password_reset_tour` (applied to the live DB):
  otp purpose `password_reset`; `users.tour_version_seen`.
* `0010_order_progress` (applied): `farmer_participations.progress`, `progress_at`.
* `0011_harvest_correction` (applied): `harvest_actuals.previous_quantity_kg`, `corrected_at`, `correction_reason`.
* `0012_crop_categories` (applied): `crops.category` accepts `fodder`, `medicinal`. After applying, run
  `python -m app.cli.seed_crops` in the backend container to add the new catalogue crops (skips existing names).

## Results (end of stage 3 session 2)
* Automated: backend 1461 passed in the full run; the 2 docs-sync failures were stale generated docs, regenerated and
  re-run (pass); later targeted runs after the farm-summary / filter changes pass (assistant, docs, vision). ruff,
  ruff format, mypy clean. Flutter: 132 tests passed in the full run, plus the market search test; `flutter analyze`
  clean.
* Direct API against the live server (test farmer `+919775823658`, "Stage3 Live Test Farmer (Claude)", farm "Stage3
  Test Farm"): register, tour, forgot/reset password (old session revoked), unknown-number reset same shape,
  catalogue (fodder/medicinal, Kannada search, 80 crops), Open-Meteo weather now, reminder past-time refusal and
  create/edit/delete, assistant general and mixed answers through Ollama, crop health with gemma3:4b on three
  real photos, history - all pass.
* Phone: debug APK installed over the existing app with data kept (firstInstallTime unchanged). The phone was
  locked/dozing, so NO on-device UI test was run in this session.

## Crop-photo analysis upgrade (2026-10-15, crop-health session)
Full report: `docs/CROP_PHOTO_ANALYSIS_2026-10-15.md`.

**Done**
* Structured, evidence-based report stored with every analysis, in English and Kannada. Sections: photo check;
  crop and part (an unverified guess); observations; possible causes; visual condition score out of 10, withheld when
  the evidence is insufficient; limitations; next step.
* Category percentages now always add up to 100 (they had shown 101 %). They are labelled as not measured
  probabilities.
* Fruit and other non-leaf photos are handled in the leaf check.
* The model's raw verdict is stored.
* Candidate prompt v2 is available behind `CROP_HEALTH_PROMPT_VERSION`, default v1.
* Flutter shows the score and the report sections.

**Tests**
* vision unit tests: 149 passed;
* full backend pytest: 1748 passed, 0 failed (22 min). Run on a private test database `harvestique_test_crophealth`, because concurrent sessions sharing `harvestique_test` reset each other's data;
* ruff clean, and mypy clean on the touched modules;
* Flutter: analyze clean, 156 passed.

**Blocked**
* The pre-registered held-out comparison of v1 and v2 (74 unseen photos) has not run. Committed memory stays at
  80–81 %, and the runner needs ≤ 75 %. Until it runs, v2 stays off.
* (Resolved) The earlier full-mypy failure in `app/schemas/pooling.py` was fixed by the pooling session. Full ruff,
  format and `mypy app` (173 files) are now clean.

**Remaining**
* Run the held-out comparison when memory allows.
* Have a native speaker review the new Kannada strings.
* Collect labelled fruit and Karnataka field photos.
