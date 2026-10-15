# Farmer–buyer interaction audit: nine app sections (2026-10-14)

Evidence levels:
* **A**: automated test run in this session against PostgreSQL (backend) or as a Flutter widget test.
* **Phone-13**: done on the real phone on 2026-10-13 with the previous build (`PHONE_TEST_REPORT_2026-10-13.md`).
  Not repeated with today's build.
* **Untested**: no evidence.

A feature only counts as *passed* when its test ran and passed. Screens loading or the APK building does not count.

How each workflow was traced: Flutter screen → API path (from the screen's code) → FastAPI router (role
dependency) → service → PostgreSQL → response → what the other role's screen loads.

The new journey test is `backend/tests/integration/test_cross_role_journey.py`. It follows one order through the
endpoints both roles' screens call and checks each side after every step.

## Farmer sections

| # | Section / feature | Interaction with the buyer | Endpoint | Test | Result |
|---|---|---|---|---|---|
| F1 | Home: requests summary | Buyer's order appears as a pending request | `GET /participations?status=pending` | journey test | Pass (A); Phone-13 |
| F2 | Home: reminders summary | (own data) | `GET /reminders?status=pending` | `test_reminder_crud_and_validation` | Pass (A) |
| F3 | Home: lots at risk | Commitments flagged when the prediction worsens | `GET /inventory/lots` | `test_a_worse_prediction_puts_commitments_at_risk_without_reallocating` | Pass (A) |
| F4 | Home: farm weather | (own farm location) | `GET /farms/{id}/weather/now` | `test_weather_now.py` | Pass (A); Phone-13 |
| F5 | My Farm: crop lifecycle | Abandoning a crop cancels its lot, so buyers no longer see it | `PATCH /crop-cycles/{id}` | `test_abandoning_the_cycle_cancels_the_lot` | Pass (A) |
| F6 | My Farm: prediction becomes supply | Only the cautious estimate (p10) is offered | `POST /crop-cycles/{id}/predictions` | `test_lot_is_created_from_the_prediction_and_promises_only_p10` | Pass (A) |
| F7 | Harvest: offer a lot (opt in, grade) | Only opted-in lots appear in buyer search | `PATCH /inventory/lots/{id}` | `test_supply_search_and_opportunities_show_only_opted_in_estimates`, journey | Pass (A) |
| F8 | Market: accept / decline requests | Buyer sees "confirmed", or the item is reallocated and the buyer is told | `POST /participations/{id}/accept`, `/decline` | journey; `test_decline_releases_supply_and_reallocates_atomically`; `test_a_decline_tells_the_buyer_directly` | Pass (A); Phone-13 |
| F9 | Market: progress (preparing → ready) | Buyer is notified once per stage | `POST /participations/{id}/progress` | journey; `test_farmer_progress_preparing_then_ready_notifies_the_buyer_once` | Pass (A); Phone-13 |
| F10 | Market: buyer opportunities | A buyer's demand is shown to farmers growing that crop | `GET /market/opportunities` | journey (opportunity plus one notification) | Pass (A) |
| F11 | Harvest: record actual harvest | Reallocates and flags shortfalls on orders | `POST /crop-cycles/{id}/harvest-actual` | `test_harvest_record_also_triggers_reallocation`, `test_a_small_actual_harvest_flags_a_shortfall` | Pass (A) |
| F12 | Harvest: correct a harvest | Allowed only until produce reaches a hub (audited) | same | `test_a_harvest_can_be_corrected_until_produce_reaches_a_hub` | Pass (A) |
| F13 | Reminders: create / edit / complete / delete; due notices | Personal; due processing is idempotent | `/reminders` | engagement suite | Pass (A); Phone-13 |
| F14 | Bell / notifications | Read state is per user | `/notifications`, `/read`, `/read-all` | journey; `test_notifications_read_and_ownership` | Pass (A); Phone-13 |
| F15 | Assistant (voice and text, EN/KN), voice navigation | Same tools and roles as the screens | `/assistant/chat`, `/assistant/voice/intent` | 6 new integration tests, 5 new widget tests, voice corpus | Pass (A); **untested on the phone with speech** |

## Buyer sections

| # | Section / feature | Interaction with the farmer | Endpoint | Test | Result |
|---|---|---|---|---|---|
| B1 | Market: supply summary | Opted-in farmer lots, as estimates | `GET /market/supply` | journey | Pass (A) |
| B2 | Market: search future harvests | Eligible lots only; no farmer contact data | `GET /market/harvests` | journey | Pass (A) |
| B3 | Demand: create | Matching farmers are told once | `POST /buyer-demands` | journey | Pass (A); Phone-13 |
| B4 | Demand: withdraw | Only before pooling; a repeat is harmless | `POST /buyer-demands/{id}/cancel` | `test_an_open_demand_can_be_cancelled_but_a_pooled_one_cannot`; journey (after an order cancel) | Pass (A); Phone-13 |
| B5 | Demand: matches → pool | Pool engine allocates; no over-allocation | `/buyer-demands/{id}/matches`, `/pool` | pooling suite (2,000 kg scenario etc.) | Pass (A) |
| B6 | Orders: place | Creates farmer requests; idempotent; one order per pool | `POST /orders` | journey; `test_order_idempotency_and_one_order_per_pool`; `test_concurrent_orders_on_one_pool_create_exactly_one` | Pass (A); Phone-13 |
| B7 | Orders: status | Shows the farmer's accept / progress | `GET /orders`, `/orders/{id}` | journey | Pass (A); Phone-13 |
| B8 | Orders: cancel | Farmer requests become "withdrawn", supply is released, the farmer is notified, the demand closes | `POST /orders/{id}/cancel` | journey (both tests) | Pass (A); Phone-13 |
| B9 | Orders: batches and traceability | Hub records; quality before fulfilment | `/orders/{id}/batches`, `/trace` | `test_full_fulfilment_and_traceability` | Pass (A) |
| B10 | Reminders | Personal | `/reminders` | engagement suite | Pass (A) |
| B11 | Bell / notifications | Read state is per user | `/notifications` | journey | Pass (A); Phone-13 |
| B12 | Assistant | **The buyer app had no button to open it** (backend supported buyers): an "Ask" button was added today | `/assistant/*` | navigation integration test (buyer tabs only) | Pass (A); untested on the phone |

## Cross-role workflows (prompt §6.9)

| # | Workflow | Result | Evidence |
|---|---|---|---|
| 1 | Farmer listing → buyer discovery | Pass | A (journey) |
| 2 | Buyer demand → farmer visibility | Pass | A (journey) |
| 3 | Reservation/order request → farmer notification and request list | Pass | A (journey); Phone-13 |
| 4 | Farmer accepts → buyer sees confirmed | Pass | A (journey); Phone-13 |
| 5 | Farmer declines → buyer told, item reallocated or warned | Pass | A (`test_a_decline_tells_the_buyer_directly`, `test_decline_without_spare_supply_leaves_the_buyer_warned`) |
| 6 | Buyer cancels → farmer updated, quantities released | Pass | A (journey); Phone-13 |
| 7 | Harvest recorded → available supply and fulfilment | Pass | A (`test_fulfil_only_after_the_measured_harvest`, `test_harvest_record_also_triggers_reallocation`) |
| 8 | Quantity reduction → shortage, feasible reallocation, honest report | Pass | A (`test_farm_c_drop_detects_exactly_250_kg_and_no_replacement_without_spare_supply`, `test_partial_replacement`) |
| 9 | Partial fulfilment / partial pool | Pass | A (`test_insufficient_supply_creates_a_partial_pool`, `test_fulfilment_counts_only_accepted_produce_and_closes_the_order`) |
| 10 | Reminders and notices for both roles, read state, no duplicates | **Partial** | A: notifications per role with dedup keys; reminder due processing is idempotent. **Gap: order events send notifications but do not create calendar reminders** (e.g. a collection date). |
| 11 | Sign-out / sign-in / restart → same records | Pass for the backend; device not re-run | DB persistence (A); Phone-13 app restart |
| 12 | Unauthorized access refused, no leaks | Pass | A (journey: another buyer gets 404, the farmer gets 403 cancelling, the buyer gets 403 accepting; authorization matrices) |
| 13 | Concurrent / duplicate requests | Pass | A (concurrency tests for orders, reservations, pools, fulfilment) |
| 14 | Network / backend failure → recoverable UI, no false success | Pass (widget level) | A (assistant retry, reloadable refresh tests); device untested today |
| 15 | Harvest-pooling regression (A–E, C drops to 200 kg → 250 kg shortage) | Pass | A (`test_critical_scenario_creates_a_2000_kg_pool_from_five_farms`, `test_farm_c_drop_detects_exactly_250_kg…`) |

## Completion percentages (from the results above)

| Area | Automated: passed / tested | Phone (any build): passed | Phone with today's build |
|---|---|---|---|
| Farmer features (F1–F15) | 15 / 15 | 8 / 15 (Phone-13) | 0 (not installed) |
| Buyer features (B1–B12) | 12 / 12 | 6 / 12 (Phone-13) | 0 |
| Cross-role workflows (1–15) | 14 / 15 pass, 1 partial (#10) | 5 / 15 | 0 |
| Security and authorization | role/ownership matrices pass; **2 open findings** (database port reachable on the LAN; no account deletion) | — | — |
| Release-critical gates (see `implementation_roadmap.md`) | 6 / 12 met | — | — |

**Not 100 %:**
* Workflow #10 is partial.
* Today's build has not been used on the phone, and voice with real speech (English and Kannada) has never been
  tested on the phone.
* Release gates are open (signing, application ID, HTTPS hosting, account deletion, privacy policy).
