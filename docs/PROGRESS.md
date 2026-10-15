# Harvestique — Project Progress

_Last updated: 2026-10-10 · after the completion pass (section 3d)_

## 1. Snapshot

| Phase | Scope | Status | Tests (cumulative) | API operations (cumulative) |
|---|---|---|---|---|
| 0 | Architecture, scaffold, health checks, validation tooling | ✅ approved | 27 | 2 |
| 1 | Backend identity: users, profiles, JWT + refresh rotation, RBAC, lockout | ✅ approved | 172 | 10 |
| 2 | Farm & crop management backend | ✅ approved | 469 | 46 |
| 3 | Farm income & land planning | ✅ approved | 883 | 60 |
| 4 | Agricultural intelligence: weather, prediction, risk, virtual inventory, feedback & calibration | ✅ approved | 1048 | 75 |
| 5 | Dynamic Predictive Harvest Pooling & Dynamic Reallocation | ✅ approved | 1139 | 86 |
| 6 | Product layer: marketplace, collection, quality, traceability, reminders, notifications, calendar, admin, demo, AI assistant, voice/vision, Flutter app | ✅ **implemented, awaiting review** (Flutter not compiled, see §3c) | **1340** | **129** |
| 7 | Final research / security audit | ⏳ not started | | |

Latest verification (Linux sandbox, PostgreSQL 16, Python 3.13):
`ruff check` clean · `ruff format --check` clean · `mypy --strict app` clean (157 files) ·
`pytest` **1340 passed, 0 failed, 0 skipped** (558 unit + 782 database-backed, one run of 6 min 53 s) · coverage
**98 %** · migrations `0001`→`0007` upgrade from empty, downgrade to base and re-upgrade · `alembic check` no drift ·
repeatable demo identical across `--reset` runs · **Flutter: not analysed, tested or built** (SDK and packages blocked
by the sandbox network policy; see §3c).

## 2. What exists today

**Backend** (`backend/`) — FastAPI modular monolith with enforced layers
(`api → services → domain / repositories → models`, providers behind Protocols; the import rules are checked by
`tests/unit/test_architecture.py`, and the pure `domain/` package may not import FastAPI, SQLAlchemy **or pydantic**).
PostgreSQL + SQLAlchemy 2.0 + Alembic (`0001_baseline → 0002_identity → 0003_farming → 0004_planning → 0005_intelligence → 0006_pooling → 0007_marketplace`).

**Frontend** (`frontend/`) — Flutter Android app connected to the real API (farmer, buyer and admin apps; §3c).

**Docs** — `ARCHITECTURE.md` (design; API & validation reference §4.1; planning engine §4.2), `DECISIONS.md`
(46 records), `DEVELOPMENT.md` (Windows setup), this file.

## 3d. Completion pass (2026-10-09/10): income planner, assistant, phone verification
Verified on the Windows development PC (Docker PostgreSQL 16, Python 3.12 in the backend image, Flutter 3.x):
backend **1,405 passed**, ruff/format/mypy --strict clean, `alembic check` no drift; Flutter `analyze` **no
issues**, **90 tests** passed; 29/29 live end-to-end checks against the running server with real Ollama and
Open-Meteo. A debug APK compiles (in a scratch copy: this folder's `android/` has no Gradle files, see
frontend/README.md). **Nothing new has been tried on a phone yet.**

* **Income planner:** the app can now add crops to a plan, by hand (catalog or own crop; a plot fills in the area)
  or from a crop's saved prediction. It shows estimated net income, revenue and costs as ranges from the engine,
  next to the expenses actually recorded on the linked farm (labelled actual; sale income is not recorded).
  * Crops can be edited or removed, and a plan can be deleted.
  * New rule: the same crop with the same sowing date cannot be entered twice (409 `duplicate_plan_item`).
  * Fixed: an empty plan opened on an error screen (the server's 409 `plan_has_no_items`). It now asks for crops.
* **Assistant:**
  * New tools: `expense_summary` and `record_expense` (proposed; saved only with confirmation).
  * `income_plans` now reports the engine's estimate.
  * Follow-up questions use history the app sends back; crop and farm names resolve to the caller's own records.
  * The local model (Ollama) is a validated fallback for tool choice and short, labelled, number-free general
    answers.
  * Fixed: Ollama availability was cached forever, and JSON mode was ignored.
  * Voice now goes through the full assistant.
  * The app has a voice-first screen (see AI_PIPELINE.md).
* **Phone verification:** registration and every login finish with a one-time SMS code (migration
  `0008_phone_verification`; existing accounts are verified by their next login). Codes are stored only as HMACs.
  * Each code expires, allows 5 wrong attempts and has a resend cooldown and limit.
  * Limits apply per phone and per client.
  * There is no account enumeration on registration, and decoys cannot block a real user's sign-in.
  * SMS providers: `dev_console` (development only, labelled, refused in production), `android_gateway` (own phone
    and SIM) or `disabled`.
* **Configuration:** production now refuses `fake` weather, LLM, speech and notification providers and the dev OTP
  mode. `.env.example` documents the new settings and their costs.
* **Fixed along the way:**
  * Weather defaulted to simulated data when no `.env` existed.
  * The demo CLI could have sent real SMS to its made-up numbers.

**Not free / not done:**
* Real SMS in production costs money (carrier SMS through the Android gateway, or a paid SMS provider), and a
  delivered SMS has not been tested from this machine.
* Kannada general AI answers are off: small local models wrote garbled Kannada.
* No background wake word (Android does not allow it).
* Server-side speech is not used: no adequate free local Kannada STT/TTS.

## 3c. Phase 6 in detail: the product layer
Docs: `API.md` and `DATABASE.md` (generated from the code and kept in sync by a test), `AI_PIPELINE.md` (assistant,
voice, vision, demo), `HARVEST_POOL.md` (default algorithm, order integration), `TESTING.md`.

**Backend**
* **Phase 5 decision applied:** new pools default to **greedy + dynamic reallocation**; the risk-capped LP and the
  ablation stay available for research only; no optimiser superiority is claimed.
* **Marketplace:**
  * buyer profiles editable; future-harvest search (`/market/harvests`, opted-in lots only, pseudonymous, p10-based);
    supply summary; farmer buyer-opportunities;
  * orders on pools (idempotent, one per pool) with an item per allocation, reusing the pool's inventory
    reservations (no new reservations, no double booking);
  * **farmer participation**: accept, or decline, which releases the supply, excludes the lot and reallocates in
    one transaction; order state machine (placed, confirmed, in fulfilment, fulfilled / partially fulfilled,
    cancelled); cancellation releases everything and closes the pool.
* **Collection and quality:** collection hubs (admin); produce batches with printable codes, only for accepted items
  after a measured harvest; one measured quality check per batch whose weights must balance and whose grade must meet
  the buyer's minimum; fulfilment counts quality-accepted produce only, capped at the farm's share, through the
  inventory's own fulfil rule; completion closes the pool.
* **Traceability:** `GET /orders/{id}/trace` covers Order → Pool → Farm allocation (with ledger) → farmer
  participation → predictions → Harvest → Collection batch → Quality → Fulfilment → prediction feedback, each step
  labelled measured / estimate / user-entered / pending. `GET /trace/batches/{code}` works backwards from a batch code.
* **Reminders** (9 types, recurrence, suggestions from recorded data only), an **in-app notification feed**
  deduplicated per event (participation, shortage/reallocation, order, collection, quality, fulfilment, buyer
  opportunity, due reminders), a **farm/delivery calendar**, and an **admin dashboard** of real counts.
* **Repeatable demo** (`python -m app.cli.demo --reset`): the scenario you specified through the real API.
  * A–E 500/350/450/300/400 kg fill a 2,000 kg greedy pool; the order is accepted by every farm.
  * Farm F joins; C 450 → 200 kg gives an exact **250 kg** shortage, fully replaced from F.
  * Harvests are recorded, then 6 batches, quality checks and fulfilment.
  * Result: **1,985 of 2,000 kg** delivered (15 kg rejected at quality, so the order is honestly
    `partially_fulfilled`).
  * Feedback for C: v1 450 kg was 114 % off the measured 210 kg; v2 200 kg was 4.8 % off.
  * All demo data is labelled simulated.
* **AI assistant, voice, vision:** see `AI_PIPELINE.md`.
  * Controlled user-scoped tools; one confirmed write tool (`create_reminder`); allocation requests refused.
  * English/Kannada templates; optional local LLM wording behind a numeric grounding check.
  * On-device speech with server STT/TTS interfaces.
  * Colour-heuristic crop-health analysis: probability-capped, NOT validated, safe file handling, photo not stored.
* Migration `0007_marketplace` (9 tables + 3 columns), 43 new operations (129 total), 201 new tests, 18 mutation
  checks.

**Flutter app** (`frontend/lib`, 48 Dart files incl. tests):
* **Auth:** sign-in/registration with role routing (farmer, buyer, admin shells); secure token storage and silent
  refresh.
* **Farmer:** Home, My Farm (farms, plots, crops, predictions with confidence, risk and data-source chips,
  observations, crop-health photos, harvest recording, prediction feedback, income plans), Market (opportunities,
  accept/decline), Harvest (inventory, offer to buyers, grade, deliveries), Reminders (suggestions, calendar), and
  the assistant with English/Kannada voice.
* **Buyer:** supply, harvest search, demands with ranked matches, pools with reallocation events and ledger, orders,
  cancellation, traceability.
* **Admin:** dashboard, orders with batch / quality / fulfil actions, quality queue, hubs.
* **UI states:** loading, error, empty and offline (last saved copy with a dated banner) everywhere; large touch
  targets.
* **Status:** **never compiled, analysed or run**. The Flutter SDK and pub packages could not be downloaded here.
  A custom string-aware static check (imports, unused imports, brackets, `sort_child_properties_last`) passes, but it
  is not a substitute for `flutter analyze`.

**Phase 6 limitations / open items.**
* **Flutter:** unvalidated (above); Android system-tray notifications are not wired (in-app feed polled every
  minute); offline writes are not queued.
* **Crop-health model:** a heuristic, not a trained or validated model.
* **Kannada:** the strings need review by a native speaker.
* **Marketplace scope:** quantities only (no prices, contracts, payments or logistics); hub operators use the admin
  role (no separate hub-operator role).
* **Dependencies:** the LLM (Ollama) and server speech engines are optional and untested against real services.

## 3b. Phase 5 in detail: harvest pooling and dynamic reallocation
Docs: `HARVEST_POOL.md`, `ALGORITHMS.md` section 8, `EVALUATION.md` (pooling experiment).

* BuyerDemand, HarvestPool, HarvestPoolMember, HarvestAllocation, HarvestReservation (= reused Phase 4 inventory
  reservation), ReallocationEvent, append-only allocation ledger; farmer opt-in and expected grade on lots.
* Matching with explainable configurable score; greedy baseline and staged risk/confidence-aware LP (SciPy HiGHS).
* Automatic shortage detection and reallocation on every prediction/harvest change; manual rebalance; both
  idempotent, transactional and lock-ordered.
* **Critical scenario:** A 500 / B 350 / C 450 / D 300 / E 400 kg fill a 2,000 kg pool; C 450 -> 200 kg is detected as
  exactly **250 kg** shortage; replaced fully (F 300 kg spare), partly (F 100 kg: 100 replaced, 150 unresolved) or not
  at all (no spare: pool `at_risk`, 1,750 kg).
* **Experiment (simulated, 480 trials):** pooling + dynamic reallocation beats static allocation at every disruption
  level (H1 supported); the risk-aware LP does not beat greedy and is worse at 50% disruption (H2 not supported; the
  risk cap is the cause).
* Migration `0006_pooling` (6 tables + 2 lot columns), 11 endpoints, 91 new tests, `python -m app.cli.pooling_experiment`.

**Phase 5 limitations.** (Default algorithm: decided in Phase 6, greedy.) No prices, contracts, per-order farmer acceptance or logistics. One pool per demand. The full
suite now exceeds 5 minutes with coverage. No mutation run for Phase 5. Phase 4 limitations still apply.

## 3a. Phase 4 in detail: agricultural intelligence
Docs: `ALGORITHMS.md`, `AI_PIPELINE.md`, `TESTING.md`, `EVALUATION.md`, `RESEARCH_CONTRIBUTION.md`.

* **Weather Intelligence:** Open-Meteo adapter (forecast + ERA5 archive) with a PostgreSQL cache; failures degrade
  to STALE (cache) or UNAVAILABLE without blocking predictions.
* **Future Harvest Prediction:** hybrid rule model behind `PredictionProvider`; p10/p50/p90 quantity, harvest window,
  confidence and risk; sources labelled measured / estimate / assumption; `insufficient_data` instead of guessing.
  **Append-only versions** with a change summary against the previous version.
* **Farm Risk Engine:** weather, disease, water, yield, market, demand, labour, timing, fulfilment; unassessed
  categories excluded, never guessed; farm-level view.
* **Virtual Harvest Inventory:** p10 committable before harvest, measured after; no negatives, over-allocation or
  double booking (code + DB + row lock); AT_RISK with shortfall when a re-prediction drops.
* **Feedback & calibration:** measured harvests score every version; calibration applied only with >= 5 outcomes;
  versioned profiles; no accuracy claimed without data.
* **Planning integration:** `POST /crop-plans/{id}/items/from-prediction`.
* Migration `0005_intelligence` (7 tables + crop reference columns), 15 endpoints, 165 new tests,
  `python -m app.cli.evaluate_simulation` (SIMULATED study), `seed_crops --fill-references`.

**Phase 4 limitations.** No real-world accuracy yet (no recorded harvests); live Open-Meteo unreachable from the
sandbox (HTTP 403), adapter tested with mocked responses only; seeded reference yields and rule constants need
agronomic review; simulated calibration reaches mean coverage 0.725, below the 0.80 target; calibration pooled across
farms per crop; inventory is farmer-managed only (buyer booking belongs to the marketplace phase).

## 3. Phase 3 in detail — farm income & land planning

### What it does
A farmer describes **land, budget, water, labour, season** and a set of **crops** (duration, costs, labour,
**yield range**, **price range**, demand, harvest timing, declared risk). The engine returns, for each crop and for
the whole plan: **estimated cost** (expected and with an overrun allowance), **yield / revenue / margin ranges**
(pessimistic · expected · optimistic), **break-even** (price, yield, margin of safety), **planning period**,
**land utilization over time**, **income continuity** (month by month), **risk level** and **confidence**, plus
findings, explanations, assumptions and a disclaimer. Nothing is a forecast or a guarantee.

| Planner | Where | What it answers |
|---|---|---|
| Cost & Income Calculator | `POST /planning/calculate` | "What would this plan cost and earn?" (stateless, nothing saved) |
| Farm Income Planner | saved scenarios `/crop-plans…` + `…/evaluation` + `/compare` + `/duplicate` | "Which of my alternatives is better, and is each feasible?" |
| Land Utilization Planner | `POST /planning/suggest-allocation` + `land` block of every result | "How should I split my land, and how busy is it month by month?" |
| Income Continuity planning | `continuity` block + staggered `batches` | "When does money come in, where are the gaps, how much cash do I need?" |

### Engine (`backend/app/domain/planning/`, pure Python)
`models.py` (validated inputs, immutable results) · `calculator.py` (arithmetic) · `scoring.py` (risk, confidence)
· `timeline.py` (land use, monthly cash flow, continuity) · `allocation.py` (greedy allocator) · `engine.py`
(`evaluate_plan`). Formulas, weights and thresholds are in `ARCHITECTURE.md` §4.2 and are named constants in code.

### Persistence (migration `0004_planning`, 2 tables)
`crop_plans` (constraints, optional farm link) and `crop_plan_items` (one crop each; ranges, costs, timing,
batches). 19 `CHECK` constraints (ordered ranges, positive areas, staggered items need an interval, …), unique
plan name per owner, items cascade with their plan, crop/farm/user links are `RESTRICT`. **Only inputs are stored;
results are recomputed on every read.**

### API — 14 new operations
`POST /planning/calculate` · `POST /planning/suggest-allocation` · `POST|GET /crop-plans` ·
`GET|PATCH|DELETE /crop-plans/{id}` · `GET /crop-plans/{id}/evaluation` · `GET /crop-plans/compare` ·
`POST /crop-plans/{id}/duplicate` · `POST /crop-plans/{id}/items` · `GET|PATCH|DELETE /crop-plan-items/{id}`.
All farmer-only; other farmers' plans are 404; buyers/admins 403; anonymous 401.

### Requirement checklist
| Requirement | How it is met |
|---|---|
| Deterministic & explainable | Pure `Decimal` engine; same input ⇒ identical result (tested). Every crop has a step-by-step `explanations` list; every risk/confidence component carries score, weight and reason; the allocator names the binding limit for each decision |
| Respect land and budget | `land_exceeded` / `budget_exceeded` are **hard** findings ⇒ `feasible=false`; land is checked **over time** (peak concurrent area). The allocator never exceeds them (600 seeded random scenarios + a 32-case grid assert this) |
| Multiple crops, staggered planting, income continuity | N crops per plan; `batches` + `batch_interval_days`; monthly income / cost / cumulative net, gaps, lead time, peak funding |
| Ranges, never guarantees | Every money/quantity output is low/expected/high; worst case pairs lowest revenue with highest cost; disclaimer + assumptions on every result; confidence is documented as *input quality*, not a probability |
| Independent of FastAPI/DB | `app/domain/planning` imports only the standard library, `app.core.enums` and `app.domain.farming`; enforced by the architecture test |
| Inputs | land, budget, water, season, crop, duration, cost, labour, yield range, price range, demand, harvest timing, risk — all supported |
| Outputs | estimated cost, yield range, revenue range, margin, break-even, planning period, risk level, confidence — all returned |

## 4. How correctness was checked (beyond "tests pass")

* **Hand-verified worked example** used across the suite (2 acres tomato: cost ₹87,000 → ₹95,700; revenue
  ₹128,000 / ₹288,000 / ₹576,000; margin ₹32,300 / ₹201,000 / ₹489,000; break-even ₹3.625/kg; risk 44.3; confidence 44.0).
  Expected values in tests are written as independent arithmetic, not copied from program output.
* **Mutation checks**: 19 deliberate defects injected one at a time (worst-case margin pairing, overrun default,
  demand cap, budget and land off-by-one, risk weight, threshold, inclusive harvest day, day-weighted income split,
  both allocator bugs found below, ranking order, batch remainder, ownership filter, compare crowning an
  infeasible plan, catalog season, role guard) — **all caught**.
* **Cross-implementation check**: the new land-usage profile is asserted equal to Phase 2's independent
  `peak_concurrent_area` over 40 generated schedules.
* **Randomised stress test** of the allocator: 3,000 scenarios run once (0 violations in 2,867 non-empty
  allocations); a 600-scenario seeded version is committed.
* **Authorization matrix** for every planning route (anonymous / buyer / admin / other farmer / owner) with a
  meta-test that fails if a route is added without being covered.
* **Database-level tests** for every `CHECK`, unique and `RESTRICT`/`CASCADE` rule, bypassing the application.
* **Live smoke test** on a database migrated from empty, with production Argon2 settings.

### Defects found *during* this phase (and fixed)
1. **DB `CHECK` let `NULL` through** — `batches = 1 OR batch_interval_days >= 1` accepts a 2-batch item with no
   interval (a NULL check result is not a violation). Fixed in model and migration; regression-tested at DB level.
2. **Allocator over-allocated a staggered crop** — it checked each batch only against *other* crops, so a crop whose
   own batches overlap could take 10 acres of a 5-acre farm (an earlier share-cap bug had been masking it).
   Fixed (exact per-day check of the crop's own overlapping batches); regression tests + randomised stress test added.
3. **Share cap applied to total area** instead of per batch, blocking legitimate land reuse by staggering. Fixed.
4. **Type-ignores hid a runtime error** in compare (raw dataclasses passed where models were expected). Removed.
5. Three of my own test expectations were wrong (income months of a staggered plan, etc.); the engine was right.

## 5. Decisions you may want to override  (full list: `DECISIONS.md` D036–D046)

| # | Decision | Why it matters |
|---|---|---|
| D036 | A plan exceeding land/budget is **saved** and flagged infeasible, not rejected | Lets farmers explore. A strict "reject on save" mode is a small change if you prefer it |
| D037/38 | Only land & budget are *hard*; budget is checked on **expected** cost | Water/labour are season totals, so warnings. Overrun risk shows as `budget_at_risk` |
| D040 | Risk/confidence weights and level thresholds (35/65, 45/70) are my judgement | **Unvalidated**: please review with an agronomist/economist; they are constants in `scoring.py` |
| D043 | Allocator is greedy, not optimal | Chosen for explainability; an LP is reserved for the Harvest Pool research work |
| D046 | Defaults: 14-day harvest window, 5/10/20 % overrun, sowing-month season calendar | Indicative only; season mismatch is a warning, never an error |
| — | Planner is farmer-only | Admins/buyers get 403, consistent with earlier phases |

## 6. Known limitations / technical debt

* Yield and price ranges are **entered by the farmer**; nothing is learned from Phase 2 history yet, and there is no
  weather or prediction input (explicitly out of scope — the future prediction work will supply these ranges).
* Costs are placed in the sowing month and revenue evenly over the harvest window with no payment delay; the budget
  check ignores reinvestment (reported separately as `peak_funding_required`).
* Water and labour are compared as season totals, not peak-week demand.
* A plan holds at most 30 crops, the allocator takes at most 20 candidates, compare takes 2–5 plans (API limits).
* Greedy allocation can miss a better split; ties are broken deterministically (name, then input order).
* `scripts/validate.ps1` (Windows) and **every Flutter check (analyze, test, build)** have still never been executed:
  Docker, PowerShell and the Flutter SDK are unavailable in the sandbox. Run them on the Windows machine.
* The backend suite takes about 7 minutes with coverage on the sandbox.
* Phase 1 carry-overs: no registration rate limit, no password reset, `login_attempts` never purged.

## 7. Explicitly **not** implemented yet

Prices, contracts, payments and logistics · Android system-tray notifications · a trained crop-health model ·
the final research and security audit (Phase 7).

## 8. How to run everything

```powershell
copy .env.example .env
powershell -ExecutionPolicy Bypass -File scripts\setup-backend.ps1
powershell -ExecutionPolicy Bypass -File scripts\run-backend.ps1      # migrates (0001-0007) + serves on :8000
cd backend
.\.venv\Scripts\python.exe -m app.cli.create_admin --phone 9876500000 --name "Site Admin"
.\.venv\Scripts\python.exe -m app.cli.seed_crops
powershell -ExecutionPolicy Bypass -File ..\scripts\validate.ps1      # lint + types + tests + drift check
```
API docs: http://localhost:8000/api/v1/docs (reference: `docs/API.md`).

Demo (separate database whose name contains "demo"):
```powershell
$env:DATABASE_URL="postgresql+psycopg://harvestique:harvestique@localhost:5433/harvestique_demo"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m app.cli.demo --reset --json   # demo logins: password Demo12345, see app/cli/demo.py
```
Flutter app: see `frontend/README.md` (`flutter create .` once, then `flutter pub get / analyze / test / run`).

## 9. Candidate next steps (to be sequenced with you)

1. Run `flutter pub get / analyze / test / build apk` on a machine with the SDK and fix what the analyzer reports.
2. Phase 7: final research and security audit (as you scheduled).
3. Android system-tray notifications (local notifications from the in-app feed).
4. A trained crop-health model behind `CropHealthClassifier` once labelled images exist; native-speaker review of
   the Kannada strings.
