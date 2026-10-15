# Algorithms

Every algorithm below is pure Python under `backend/app/domain/` (no FastAPI, SQLAlchemy or pydantic; enforced
by `tests/unit/test_architecture.py`). Arithmetic uses `Decimal`; results are rounded half-up only when built.
Constants are quoted from the code.

## 1. Land capacity (Phase 2, `domain/farming.py`)
Peak concurrent area of crop cycles on a plot by a sweep line over **inclusive** date ranges (land is freed the day
after the last occupied day). A cycle ends at its actual harvest date, else its expected harvest date, else sowing +
the crop's typical duration. Cycles that would put more land in use at once than the plot has are rejected.

## 2. Farm income planning (Phase 3, `domain/planning/`)
cost/acre = inputs + labour person-days x wage; expected cost = cost/acre x area + fixed; high cost = expected x
(1 + overrun %, default 5/10/20 % for low/medium/high declared risk). production = yield range x area; sold =
min(production, demand); revenue = sold x price (low x low, expected x expected, high x high). Margin: **low = low
revenue - high cost**, expected = expected - expected, high = high revenue - expected cost. Break-even price,
conservative price, yield and margin of safety follow. Land use is a step-function profile over time; income is
spread evenly over each harvest window. Risk/confidence are weighted sums of named components (`scoring.py`; weights
in `ARCHITECTURE.md` section 4.2). The allocator is a deterministic greedy fill limited by land (time-aware, incl. a
crop's own overlapping batches), budget, water, labour, demand, a per-batch share cap and the crop's maximum.

## 3. Weather features (Phase 4, `domain/weather.py`)
Over the days inside a window (missing days lower `coverage`; nothing is interpolated): coverage, mean temperature,
growing degree days (base `GDD_BASE_C = 10` C), rainfall, heat-stress days (Tmax >= `HEAT_STRESS_C = 35` C),
extreme-heat days (>= `EXTREME_HEAT_C = 38` C), heavy-rain days (>= `HEAVY_RAIN_MM = 64.5` mm, the IMD "heavy rain"
threshold) and the longest dry spell (consecutive days < `DRY_DAY_MM = 1` mm; a data gap breaks the spell rather
than being assumed dry).

## 4. Harvest prediction: hybrid rules (`domain/prediction/engine.py`, `hybrid-rules` 1.0.0)
Used because no real training data exists. Deterministic for identical inputs (tested).
Not predictable: abandoned cycles (`cycle_abandoned`), harvested cycles (`cycle_harvested`).

**Base yield per acre** = evidence-weighted mean of what exists:

| Evidence | Kind | Weight |
|---|---|---|
| the owner's recorded harvests of this crop | measured | 2 per record, max 10 |
| the farmer's estimate (range) | estimate | 3 |
| catalog reference yield | assumption | 1 |

No evidence -> `insufficient_data`: no quantity, confidence 0, timing still given.
Base CV = weight-averaged CV of evidence that has one (history needs >= 3 records; an estimate's CV is
(high - low) / (2 x 1.2816 x expected)); otherwise `DEFAULT_CV = 0.30`.

**Multiplicative factors** (each stored with its provenance):

| Factor | Rule |
|---|---|
| water_deficit | rainfed/unknown irrigation, >= 14 days elapsed, weather coverage >= 50 %, water need known: ratio = rain so far / (need x elapsed/duration); if ratio < 0.6: x (1 - 0.25 x (0.6 - ratio)/0.6) |
| heat_stress | x (1 - min(0.20, 0.01 x heat-stress days)) |
| heavy_rain | x (1 - min(0.10, 0.03 x heavy-rain days)) |
| field_observation | latest observation <= 30 days: x (1 - loss %), else healthy 1 / stressed 0.95 / pest 0.92 / disease 0.90 / damaged 0.85 |
| calibration_bias | only with a sufficient calibration profile: x bias factor |

**CV** = max(0.10, base CV) + widenings, x calibration interval scale (sufficient profiles only), clamped to
[0.10, 0.80]. Widenings: weather unavailable +0.10, stale +0.05, < 50 % weather coverage +0.05, recent
pest/disease/damage +0.05, time remaining +0.10 x fraction of season left.

**Quantiles** (approximately normal, `Z90 = 1.2816`): p50 = base x factors x area;
p10 = max(0, p50 (1 - 1.2816 CV)); p90 = p50 (1 + 1.2816 CV).

**Timing.** Anchor = the farmer's expected harvest date, else sowing + typical duration. With >= 7 days of observed +
forecast temperature, remaining days are scaled by 15 / (mean temperature - 10), bounded to [0.8, 1.2]. Spread =
max(3, duration x (0.05 + 0.10 x season left)) days, +3 without weather, and >= 1.2816 x calibrated mean date error.
start p10/p50/p90 = p50 -/+ spread (p10 not before sowing + 1); end = start p90 + harvest span (vegetable, fruit,
spice 30; flower 20; other 10 days). A passed anchor gives p50 = today with a warning.

**Confidence** (0-100): evidence 0.35 (>= 5 records 90; 3-4 75; 1-2 60; estimate only 50; reference only 30), weather
0.25 (fresh 90; partial 60; stale 50; none 20), observations 0.15 (<= 14 days 90; <= 30 days 60; none 30), season
progress 0.25 (elapsed %, min 10). Levels: low < 45 <= medium < 70 <= high. With a sufficient profile:
0.7 x heuristic + 0.3 x min(100, empirical coverage / 0.8 x 100), basis "calibrated"; otherwise basis "heuristic"
and the note states it is not a measured accuracy.

## 5. Farm Risk Engine (`domain/prediction/risk.py`)
Nine categories, each 0-100 or **not assessed** (score None, `insufficient_data`) when its data is missing.
Unassessed categories are excluded from the overall mean, and the report states how many were assessed.

| Category | Needs | Rule |
|---|---|---|
| weather | weather data | min(40, 4 x heat days) + min(30, 10 x heavy-rain days) + min(30, 10 x forecast extreme days) |
| disease | observation <= 30 days | healthy 10, stressed 40, pest 70, disease 75, damaged 85; + loss % / 2 |
| water | >= 7 days weather, water need | rain deficit % (x 0.3 if irrigated) + longest dry spell |
| yield | quantity prediction | 150 x CV + 100 x (1 - product of factors) |
| market | price range supplied | price spread x 100 |
| demand | demand quantity supplied | max(0, (p50 / demand - 0.8) x 150) |
| labour | need and availability supplied | max(0, (need / available - 0.7) x 200) |
| timing | always | 2 x spread days + 3 x abs(predicted - expected start) |
| fulfilment | quantity prediction | nothing committed 0; <= p10 15; <= p50 50; > p50 85 |

Scores are clamped to 0-100. Levels: low < 35 <= medium < 65 <= high.

## 6. Virtual harvest inventory (`domain/inventory.py`)
committable = 0 if the cycle is abandoned (CANCELLED); else the measured actual if recorded (HARVESTED); else the
prediction's **p10** (OPEN); else 0. committed = active + fulfilled reservations; available = max(0, committable -
committed); shortfall = max(0, committed - committable), and > 0 means AT_RISK. A reservation is refused if quantity
<= 0, the lot is cancelled, the booking key was used on the lot before, or quantity > available. Fulfilment needs a
measured harvest and an active reservation. Nothing is re-allocated automatically. The service row-locks the lot for
every change; the database enforces non-negative quantities and unique (lot, booking key).

## 7. Feedback and calibration (`domain/prediction/calibration.py`)
Per prediction version vs the measured harvest: signed and absolute error (actual - p50), absolute % error (none when
the actual is 0), whether p10 <= actual <= p90, mean pinball loss at tau = 0.1/0.5/0.9, date error (actual start -
predicted p50 start) and whether it fell inside the predicted window.
Calibration uses one outcome per harvested cycle (its last usable prediction) and is applied only with
`MIN_SAMPLES = 5` or more outcomes. bias = median(actual / p50) bounded to `BIAS_BOUNDS = [0.7, 1.3]`; interval scale
= the 80th percentile (`TARGET_COVERAGE = 0.8`) of |actual - bias x p50| / ((p90 - p10)/2), bounded to
`SCALE_BOUNDS = [0.5, 3.0]` (a split-conformal-style rule). A consistent bias is therefore corrected by the bias
factor rather than by widening. Below the minimum the profile is stored as insufficient with bias = scale = 1.
Profiles are versioned per scope (`crop:<id>`, `global`) and never overwritten.

## 8. Harvest pooling (Phase 5, `domain/pooling/`)

**Eligibility** (`matching.evaluate`): same crop; lot grade >= demand minimum (A > B > C); lot opted in; lot open or
harvested with a prediction; available > 0; lot window (prediction start p10 to end p90) overlaps the delivery
window; confidence >= demand minimum; risk <= demand maximum (unassessed risk passes); within the maximum distance
(haversine), and a lot without coordinates is ineligible when a distance limit is set. Every failure is a named reason.

**Score** (0-100, weights configurable per pool, must sum to 1; defaults in brackets):
confidence (0.25), safety = 100 - risk (0.20), reliability x 100 (0.15), window = overlap days / lot window days
x 100 (0.15), proximity = (1 - distance / max distance) x 100 (0.10), availability = min(1, available / need) x 100
(0.15). Unknown risk or distance scores a neutral 50. Reliability = (predictions whose actual fell inside p10-p90
+ 1) / (scored predictions + 2) per farmer (Laplace smoothing; 0.5 with no history).

**Greedy baseline** (`optimizer.greedy`): eligible lots by score (ties by lot id), each takes
min(available, remaining need).

**Harvestique LP** (`optimizer.lp`, HiGHS via SciPy):
stage 1: T1 = max sum(x) s.t. sum(x) <= need, 0 <= x_i <= available_i, sum((risk_i - R) x_i) <= 0 (average pool risk
<= R, default 50; unassessed risk counts as 50); stage 2: the same with x_i <= share x need (default 40%), kept only
if it reaches T1, so diversification never costs fulfilment; stage 3: maximise sum(score_i x_i) at that total.
Quantities are floored to whole grams and any rounding gap is topped up from the lowest-risk lines within limits.

**Shortage** (`shortage`): lot shortfall = max(0, committed - committable); assigned to pool commitments newest first
(by original allocation time); farmer reservations are never cut. Pool status: `at_risk` if an unresolved shortage
or a committed lot is over-committed; else `filled` / `partial` / `unfilled`.

**Experiment** (`experiment`, simulated): 30 farms, 4 competing pools each demanding 22% of total p10, disruption
of a fraction of farms (yield x U(0.3, 0.7)), mid-season revised predictions, all strategies committing at p10.
Full description in `EVALUATION.md`.
