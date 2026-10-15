# Dynamic Predictive Harvest Pooling and Dynamic Reallocation (Phase 5)

Buyers commit to **future** harvests pooled across several farms. Supply is uncertain, so the pool only ever uses
each farm's **p10-based committable quantity** (Phase 4 inventory), detects shortages when predictions change, and
replaces lost supply automatically, with a full audit trail. Algorithms: `ALGORITHMS.md` section 8.

## Entities
| Entity | Table | Notes |
|---|---|---|
| BuyerDemand | `buyer_demands` | crop, quantity, delivery window, minimum grade, optional delivery point + max distance, min confidence, max risk |
| HarvestPool | `harvest_pools` | one per demand; algorithm (`lp` or `greedy`), weights, risk cap, share cap, status, allocated/shortage, idempotency key, optimistic version |
| HarvestPoolMember | `harvest_pool_members` | each farm lot that supplied the pool, with its latest score and score components |
| HarvestAllocation | `harvest_allocations` | quantity a lot supplies to a pool; status and risk level; points to its reservation |
| HarvestReservation | **`inventory_reservations` (Phase 4)** | reused, not duplicated: booking key `pool:<pool id>:v<n>`; the inventory's availability check, row lock and unique booking key therefore apply to every pool commitment |
| ReallocationEvent | `reallocation_events` | append-only; trigger, exact shortage, replaced / unresolved / topped-up kg, outcome, steps, duration, reason, before/after snapshots, unique idempotency key |
| Allocation ledger | `allocation_ledger` | append-only; every quantity change with before/after, action, reason, event and actor |
| Farm consent | `inventory_lots.pool_eligible`, `expected_grade` | a farmer must opt a lot in before any pool can use it |

## Lifecycle
1. A buyer creates a demand (`POST /buyer-demands`) and can preview ranked supply (`GET /buyer-demands/{id}/matches`),
   including ineligible lots with their reasons.
2. `POST /buyer-demands/{id}/pool` locks the demand and every lot of the crop (id order), ranks eligible supply, runs the
   pool's algorithm, and reserves each allocation through the inventory. One transaction; safe to repeat with the same
   `Idempotency-Key`.
3. When a farm's prediction (or recorded harvest) changes, every pool using that lot is rebalanced automatically, each
   in its own transaction. A failure leaves that pool exactly as it was (logged); the prediction itself is kept.
   `POST /pools/{id}/rebalance` (Idempotency-Key required) does the same on demand.
4. `GET /pools/{id}/events` and `/ledger` explain every change.
5. **Buyer-first (2026-10-15):** when supply appears after a demand was pooled short (a farmer opts a lot in,
   changes its grade, or a new/higher prediction leaves it with available quantity), every open pool of the same
   crop that is still below its demand and for which the lot is *eligible* (dates, grade, distance, confidence,
   risk) is topped up, oldest pool first, by an ordinary rebalance (trigger `supply_added`, `trigger_ref` = lot id,
   own transaction, idempotent key). Pools the lot does not fit get no event. The new farmer gets a pending order
   item to accept; nothing is confirmed on their behalf. The buyer is told "New supply found for your demand".
   `POST /pools/{id}/rebalance` ("Check for new supply") still works and is then normally `no_change`.

## Buyer-facing demand state (2026-10-15)
`DemandOut.stage` is derived (no new column) from the demand, its pool and its order (`domain/pooling/shortage.py`):
`matching_supply_available` / `partially_matched` / `no_matching_supply` for an **open** demand (live matching,
nothing reserved; `matched_kg`, `shortage_kg` filled), then the pool/order states `supply_reserved`,
`partially_matched`, `no_matching_supply`, `awaiting_farmer_confirmation`, `confirmed`, `reallocation_required`,
`in_fulfilment`, `fulfilled`, `partially_fulfilled`, `cancelled` (`allocated_kg`, `remaining_kg`, `pool_id`,
`order_id` filled once pooled). `GET /buyer-demands/{id}/matches` and `GET /market/harvests` also return
`fulfilment` (full/partial/none), `shortage_kg`, `excluded_reasons`, `explanation` and `next_steps`
(`domain/pooling/matching.py:summarize`). Farmer lots (`/inventory/lots`) return `awaiting_confirmation_kg`,
`confirmed_kg` and `fulfilled_kg` from the order items on the lot.

## Reallocation steps (as implemented)
1. lock the pool, then all lots of the crop in id order; refresh each lot from its latest prediction
2. for every allocation whose lot now promises less than is committed, compute the lot's **exact** shortfall
3. assign it to pool reservations **newest commitment first** (by when the allocation was first made); farmers' own
   reservations are never cut by the system
4. shrink the affected reservations (a reduction needs no availability check, so cuts compose in any order)
5. rank eligible replacement supply for the pool's total missing quantity and allocate it with the pool's algorithm
6. update pool totals, status and allocation risk levels
7. write a `ReallocationEvent` (outcome `full` / `partial` / `none` / `top_up` / `no_change`) and ledger rows with reasons

## States
Pool: `filled`, `partial` (created short of supply), `at_risk` (unresolved shortage after a drop, or a lot over
committed), `unfilled`. Allocation: `active`, `reduced`, `released`, `fulfilled`, plus the lot's latest risk level.

## Guarantees and how they are enforced
| Guarantee | Enforcement |
|---|---|
| never exceed available predicted supply | plans use only `available_kg` (p10 minus commitments); every reservation passes the inventory check under the lot lock |
| no negative inventory | domain clamps + DB CHECKs on lots, allocations, ledger and events |
| no double booking | unique (lot, booking key); one pool per demand; unique (pool, lot) allocation |
| no over-allocation under concurrency | fixed lock order (demand/pool, then lots by id); tested with a barrier race |
| idempotency | pool creation by (buyer, Idempotency-Key); events by unique key (`prediction:<id>:<pool>` or `manual:<pool>:<key>`) |
| atomicity | one commit per operation; rollback on any error (tested by injecting a crash mid-reallocation) |
| preserve confirmed quantities | newest-first cutting; replacements only add |
| complete audit | ledger replays to the exact current allocation (tested); events store before/after snapshots |

## Critical scenario (integration test, real PostgreSQL)
Farms A 500, B 350, C 450, D 300, E 400 kg; demand 2,000 kg. Both algorithms allocate exactly A 500, B 350, C 450,
D 300, E 400 (pool `filled`). Farm C's prediction changes 450 -> 200 kg:

| Variant | Shortage | Replaced | Unresolved | Pool after |
|---|---|---|---|---|
| no spare supply | **250 kg** | 0 | 250 | `at_risk`, 1,750 kg |
| new farm F with 300 kg | **250 kg** | 250 (from F) | 0 | `filled`, 2,000 kg; F keeps 50 kg available |
| new farm F with 100 kg | **250 kg** | 100 | 150 | `at_risk`, 1,850 kg |

## Default algorithm (decided in Phase 6)
New pools use **greedy allocation + dynamic reallocation** by default (`algorithm: "greedy"`). The simulated Phase 5
evaluation found greedy reallocation at least as good as the risk-capped LP at every disruption level and better at
50% disruption, and the ablation traced the LP's deficit to its risk cap. The LP (`algorithm: "lp"`), its risk cap
and the ablation remain available for research comparison; no superiority is claimed for the optimiser.

## Phase 6 integration
Orders are placed on pools (`POST /orders`); each allocation becomes an order item that its farmer accepts or
declines. **Declining releases that farm's supply, excludes the lot from the pool and runs the same reallocation in
the same transaction** (trigger `farmer_declined`). After every committed reallocation the order is re-synced
(new items for replacement farms, reduced/removed items, farmers asked again if their quantity grows) and the
buyer and affected farmers are notified once per event. Cancelling an order releases every open allocation and
**closes** the pool; fulfilment converts each allocation's reservation into a fulfilled one (after a measured
harvest and a quality check) and closes the pool when the order completes. Closed pools are never rebalanced.

## Limits
Quantities only: no prices, contracts or payments (a buyer's maximum price cannot be filtered on). Kilograms only:
the API has no unit conversion. One pool and one order per demand. Reallocation is triggered by prediction/harvest
changes, new or newly offered supply (top-up), farmer declines or manually, not on a schedule. Opting a lot OUT does
not withdraw allocations it already has (the farmer declines the request instead).
