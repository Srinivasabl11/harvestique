# Research Contribution

## Aim
Dynamic Predictive Harvest Pooling: let buyers commit against **predicted** supply pooled across farms, with
uncertainty handled explicitly, and repair commitments automatically when predictions change.
Phase 4 built the uncertainty foundation; Phase 5 implements pooling and dynamic reallocation (`HARVEST_POOL.md`).

## What Phase 4 contributes (implemented and tested)
1. **Uncertainty-aware prediction without training data.** A transparent hybrid rule model that outputs p10/p50/p90
   quantities and a harvest window, widens uncertainty for every missing or stale input, records each adjustment
   with its data provenance, and returns `insufficient_data` rather than a guess.
2. **Safe commitment against uncertain supply.** A virtual inventory that promises only the pessimistic (p10)
   quantity before harvest, switches to the measured quantity after harvest, and prevents negative quantities,
   over-allocation and double booking in both code and database. Lower re-predictions surface an explicit shortfall
   instead of silently reallocating.
3. **Honest risk reporting.** Nine risk categories where missing inputs are reported as unassessed and excluded,
   never estimated.
4. **A closed feedback loop with gated calibration.** Every prediction version is scored against the measured harvest;
   bias and interval width are calibrated only after a minimum number of outcomes, and profiles are versioned.
5. **Integration with economic planning.** Prediction ranges flow into the Phase 3 income planner.

## What Phase 5 contributes (implemented and tested)
6. **Pooled commitments on uncertain supply** across farms, matched on crop, grade, window overlap, confidence, risk,
   availability, reservations, reliability and location, with an explainable configurable score.
7. **Two allocators:** a staged risk/confidence-aware LP (HiGHS) and a greedy baseline, both provably limited to
   p10-based available supply.
8. **Dynamic reallocation:** exact shortage detection on prediction change, newest-first cutting that preserves older
   commitments, ranked replacement, and an append-only event + ledger explaining every change. Transactional,
   concurrency-safe and idempotent (tested), reusing the Phase 4 inventory instead of duplicating it.

## Hypotheses and what was tested
* **H1 (pooling + dynamic reallocation vs static allocation, at comparable p10 confidence): SUPPORTED in simulation**
  at every disruption level tested (fulfilment +0.7 to +13.1 points; 95% CIs exclude 0). Most of the gain comes from
  reallocating at all: greedy reallocation gains as much.
* **H2 (risk/confidence-aware LP beats greedy): NOT SUPPORTED in simulation.** No difference at 10-25% disruption,
  significantly worse at 50% (-2.4 points). An ablation shows the risk cap is responsible. In the simulated world,
  disruption is independent of risk, so this is a test of the cap's *cost*; its benefit when risk predicts disruption
  is untested.
* **H3 (gated calibration on real data): untested**: no real harvests yet; the simulated study supports the method only.

## Evidence so far
Correctness: 1,139 automated tests, 98 % coverage, mutation checks across Phases 1-4 (`TESTING.md`).
Method: two SIMULATED studies (`EVALUATION.md`): calibration (coverage 0.611 to 0.725, below the 0.80 target) and
pooling (480 trials; H1 supported, H2 not supported). No real-world data exists for either.

## Limitations
Rule constants and seeded reference yields are judgement calls needing agronomic review; reanalysis weather is
model-based, not on-farm measurement; calibration is pooled across farms per crop; the live Open-Meteo service has
not been exercised from the development environment; the pooling experiment uses one crop, independent disruptions and
synthetic risk scores, and does not model a separate single-farm "individual sourcing" baseline.
