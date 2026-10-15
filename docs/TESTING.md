# Testing

## How to run
```powershell
powershell -ExecutionPolicy Bypass -File scripts\validate.ps1     # ruff, format, mypy, pytest, alembic drift
cd backend
.\.venv\Scripts\python.exe -m pytest -m "not integration"        # DB-free subset, ~2 s
```
Database tests need `TEST_DATABASE_URL` pointing at a database whose name contains "test" (a guard refuses
others). Without it they are **skipped** (listed by `-ra`), never silently passed. The suite applies the real
Alembic migrations once per session and truncates tables between tests.

## Latest run (2026-10-10, Windows PC, Docker PostgreSQL 16, Python 3.12 in the backend image)
* Backend: `pytest` **1,405 passed, 0 failed** (13 min). `ruff check`, `ruff format --check` and `mypy --strict app`
  are clean, and `alembic check` reports no drift.
* Flutter: `flutter analyze` **no issues**; `flutter test` **90 passed**.
* Live: 29/29 end-to-end checks against the running server: OTP registration and login, Add crop → Farm crops, the
  planner with hand-checked numbers, expenses with confirmation, Kannada answers, real Open-Meteo weather, and real
  Ollama routing and general answers.
* New test files:
  * backend: `tests/integration/test_auth_otp.py`, `test_assistant_conversation.py`, `test_plan_workflow.py`;
  * Flutter: `test/features/auth/otp_screen_test.dart`, `assistant/assistant_screen_test.dart`,
    `planning/plan_forms_test.dart`, `planning/plans_screen_test.dart`, `farm/expenses_screen_test.dart`.
* (2026-10-15: SMS codes were removed; `test_auth_otp.py` and `otp_screen_test.dart` were replaced by
  `test_password_change.py` and `password_auth_test.dart`.)
* Not tested: speech and SMS on a real phone. In tests the phone's speech engines are a scripted `VoiceEngine` and
  SMS delivery is a recording sender (`RecordingSms`). The Android SMS gateway adapter is tested against a mocked
  HTTP server, not a real phone.

## Previous run (Phase 6, Linux sandbox, PostgreSQL 16, Python 3.13)
**1340 passed, 0 failed, 0 skipped** (558 unit + 782 database-backed) in one run (6 min 53 s with coverage);
line coverage **98 %** (236 of 9,794 statements not covered); ruff and ruff-format clean; `mypy --strict` clean on
157 files. The 1,139 tests that existed before Phase 6 were first run unchanged against the new code and all passed.
One Phase 0 test was deliberately updated: it asserted that the `ollama` and `in_app` providers were "not implemented
yet"; it now asserts that they are built.

**Flutter:** `flutter analyze`, `flutter test` and `flutter build` have **not** been run (the Flutter SDK, pub.dev and
Android SDK hosts are blocked in the sandbox). 6 Dart test files exist (JSON readers, formatters, offline-cache
fallback, shared widgets, login validation, and the existing status screen). The only check performed was a
string-aware static script: imports resolve and are used, brackets balance, no `print`, and `child` arguments come
last. It was self-tested on deliberately broken files.

## What is tested, and how
| Layer | Technique |
|---|---|
| Pure algorithms | unit tests with **hand-computed expected values** written as independent arithmetic |
| Allocator and engine invariants | grid and **seeded randomised** scenarios (600 committed) asserting no limit is ever broken |
| Two independent implementations | Phase 4 land-usage profile asserted equal to Phase 2 `peak_concurrent_area` |
| External API | Open-Meteo adapter with `httpx.MockTransport`: success, gaps, HTTP 500, invalid JSON, error payload, malformed payload, timeout |
| Failures and missing data | failing weather provider, no coordinates, stale cache (clock moved 13 h), insufficient evidence, old observations |
| Versioning | two prediction versions; version 1 re-read byte-identical; row counts checked |
| Concurrency | barrier-synchronised races: plot creation (Phase 2) and inventory reservations (Phase 4); exactly one may win |
| Database guarantees | raw-SQL tests for every CHECK, UNIQUE and RESTRICT/CASCADE rule, bypassing the application |
| Authorization | per-phase **matrices**: anonymous 401, wrong role 403, other farmer 404, owner 200; meta-tests fail if a route exists in no matrix |
| Determinism and reproducibility | repeated evaluation equal; simulated study identical across runs and processes |
| Mutation checks | defects injected one at a time to prove the tests catch them (below) |

## Phase 4 test files
| File | Tests |
|---|---|
| `tests/unit/test_weather_domain.py` | 5 |
| `tests/unit/test_prediction_engine.py` | 32 |
| `tests/unit/test_prediction_risk_and_calibration.py` | 24 |
| `tests/unit/test_inventory_domain.py` | 12 |
| `tests/unit/test_open_meteo_and_bridge.py` | 12 |
| `tests/integration/test_predictions_api.py` | 24 |
| `tests/integration/test_inventory_api.py` | 16 |
| `tests/integration/test_feedback_calibration_api.py` | 14 |
| `tests/integration/test_intelligence_authorization.py` | 8 |
| `tests/integration/test_intelligence_schema.py` | 18 |
| **Phase 4 total** | **165** |

## Phase 5 test files (harvest pooling)
| File | Tests | Covers |
|---|---|---|
| `tests/unit/test_pooling_domain.py` | 41 | critical scenario, every eligibility reason, score arithmetic, greedy vs LP (risk cap, diversification cap and its relaxation), never exceeding availability/need, newest-first cuts, farmer reservations never cut, pool states, experiment reproducibility |
| `tests/integration/test_pooling_api.py` | 27 | critical scenario (greedy and LP), exact 250 kg shortage, full / partial / multi-farm / no replacement, ineligible replacements (not opted in, grade, distance), prediction increase (top-up and no-change), insufficient and no supply, competing pools sharing a lot (both processing orders), farmer reservations respected, idempotent pool creation and rebalance, duplicate triggers, rollback on a crash mid-reallocation (automatic and manual), concurrent pool creation race, already-committed supply, ledger replay, released reservations kept, harvest-triggered reallocation |
| `tests/integration/test_pooling_authorization.py` | 8 | matrix for all 11 routes + meta-test |
| `tests/integration/test_pooling_schema.py` | 15 | demand, pool, allocation, event and ledger constraints at DB level |
| **Phase 5 total** | **91** | |

Defects found by these tests during Phase 5 and fixed: (1) pool booking keys exceeded the 80-character reservation-key
column; (2) resizing a reservation made it look like the newest commitment, breaking newest-first cutting;
(3) an older pool's reduction failed when processed before a newer pool's (the lot was still over-committed). This was
order-dependent (pool UUID order): it passed and failed intermittently until fixed with a reduction path that needs no
availability check, and two deterministic tests now force both processing orders (10/10 repeated runs passed).

## Phase 6 test files
| File | Tests | Covers |
|---|---|---|
| `tests/unit/test_marketplace_domain.py` | 38 | order state machine, participation transitions, cancel rules, quality validation (balance, grade minimum), fulfilment cap, batch codes |
| `tests/unit/test_assistant_domain.py` | 35 | English/Kannada intents incl. allocation refusal, language detection, reminder slots (no date = ask), grounding check (invented numbers and prices rejected, Kannada digits), every template in both languages |
| `tests/unit/test_vision_and_media.py` | 40 | crop-health heuristic on synthetic images, probability cap, quality flags, file validation (magic bytes, corrupt, oversized, tiny, animated, decompression bomb), audio magic, speech providers, Ollama failures, demo predictor and its production ban |
| `tests/unit/test_docs_in_sync.py` | 2 | API.md and DATABASE.md equal the generated output |
| `tests/integration/test_marketplace_api.py` | 20 | orders, idempotency, accept/decline, decline-driven reallocation (atomic; rollback on crash), prediction drop/increase updating orders, cancellation and pool closure, batch/quality/fulfilment rules, traceability (order and batch code), market search/supply/opportunities, concurrent orders and fulfilment, notification dedup on replay |
| `tests/integration/test_engagement_api.py` | 11 | reminders CRUD and recurrence, due reminders notified once (3 concurrent workers), notification ownership, data-driven suggestions, calendar, dashboard, profile updates |
| `tests/integration/test_assistant_api.py` | 28 | role-scoped tool catalogue with one confirmed writer, user scoping (foreign IDs unreachable), confirmation requirement, argument validation, allocation refusal, Kannada answers, grounded vs ungrounded LLM wording, empty states, failing services, voice subset, speech 503 and audio validation, crop-health upload safety and owner scoping, photos not stored |
| `tests/integration/test_phase6_authorization.py` | 10 | 401/403/404/200 matrix for all 43 new operations + meta-test |
| `tests/integration/test_marketplace_schema.py` | 15 | database constraints of every new table |
| `tests/integration/test_demo.py` | 2 | the full demo scenario and the reset guard |
| **Phase 6 total** | **201** | |

## Mutation checks (Phase 6)
18 defects injected one at a time (scripted, restoring the file after each); all are caught:
* **assistant safeguards:** write tool without confirmation, tool role check removed, assistant ignoring farm
  ownership, LLM grounding bypassed, allocation requests not refused;
* **marketplace rules:** quality balance unchecked, grade minimum unchecked, fulfilment not capped at the farm's
  share, declined lot not excluded, closed pools still rebalanced, batch without a recorded harvest;
* **concurrency, atomicity and dedup:** fulfilment row lock removed (race test), decline not atomic with
  reallocation, notification dedup removed;
* **file safety and output limits:** image magic-byte check removed, probability cap removed;
* **access and configuration:** another buyer's order visible, demo provider allowed in production.

Two were missed at first and the tests were strengthened:
* the fulfilment cap: no test delivered more than a farm's share;
* notification dedup: reminders have their own per-occurrence guard, so a replayed reallocation sync now tests it
  directly.

## Mutation checks (manual, Phase 4)
16 defects injected one at a time, each caught by the suite: negative p10 allowed; missing weather not widened;
calibration applied when insufficient; a silent default yield instead of `insufficient_data`; stale observations used;
irrigated plots penalised for rain; history weight ignored; risk guessing an unsupplied category; calibration minimum
ignored; inventory promising more than p10; negative availability; over-allocation check removed; duplicate-booking
check removed; reservation row lock removed (race test fails); version 1 overwritten; prediction ownership filter
removed. (Two of these first ran incorrectly because of mistakes in my own mutation scripts and were re-run.)
Earlier phases: 5 (Phase 1), 12 (+3 semantic, Phase 2) and 19 (Phase 3) mutations, all caught. No manual mutation run was done for Phase 5.

## Known gaps
* The live Open-Meteo service was **not** reachable from the development sandbox (HTTP 403 from the egress proxy);
  the adapter is verified only against recorded/mock responses.
* `scripts/validate.ps1` and the Flutter checks have never been executed (no PowerShell, Docker or Flutter SDK in the sandbox).
* The crop-health heuristic is tested on synthetic images only; there is no labelled crop-image evaluation.
* Optional external engines (Ollama, server speech) are tested with mocks and fakes only.
* Mutation testing is manual (no mutation tool), so it samples the safeguards rather than every line.
