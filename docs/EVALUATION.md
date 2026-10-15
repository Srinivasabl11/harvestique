# Evaluation

## What can and cannot be claimed today
There is **no real-world accuracy result**. No farm has recorded harvests in this system yet, so prediction error,
interval coverage and calibration on real data are unknown. Calibration is never applied with fewer than 5 recorded
outcomes, and the API labels confidence "heuristic, not a measured accuracy" until then.

What exists is (1) correctness evidence for the algorithms (`docs/TESTING.md`) and (2) a **SIMULATED** study of the
calibration method, below.

## Simulated calibration study (synthetic data)
`app/domain/prediction/simulation.py`; reproduce with `python -m app.cli.evaluate_simulation`.

**Design.** For each seed, 200 synthetic harvests of one crop are drawn as 9,000 x exp(N(0, 0.30) - 0.045) kg per
acre (true CV about 0.30, true mean about 10 % below the catalog reference of 10,000). The rule model predicts every
cycle from the reference only, with a deliberately over-confident reference CV of 0.15 (other inputs: fresh weather
status without daily rows, 90 of 100 days elapsed). Outcomes 1-100 calibrate the model; coverage of the p10-p90 range
and MAPE are measured on outcomes 101-200 before and after calibration.

**Results (seeds 1-20).**
```
SIMULATED calibration study (synthetic data; not real-world accuracy)
seed  cov_before  cov_after  mape_before  mape_after  bias   scale
   1       0.600      0.690        28.92       23.67  0.8631  1.1316
   2       0.670      0.700        27.10       22.19  0.7976  1.0913
   3       0.650      0.790        31.09       21.45  0.8098  1.3131
   4       0.690      0.760        26.75       21.22  0.8784  1.1884
   5       0.500      0.790        38.33       30.07  0.8755  1.4447
   6       0.600      0.700        30.52       25.42  0.8652  1.2045
   7       0.710      0.790        29.78       25.23  0.9058  1.3020
   8       0.540      0.720        31.88       28.92  0.9525  1.2591
   9       0.630      0.770        31.96       23.13  0.8504  1.2349
  10       0.600      0.650        36.39       25.95  0.8028  1.0875
  11       0.540      0.650        35.04       30.21  0.9169  1.1452
  12       0.550      0.690        33.73       29.09  0.9316  1.3092
  13       0.650      0.760        28.89       25.62  0.9430  1.2659
  14       0.560      0.660        31.45       24.83  0.8564  1.1142
  15       0.550      0.720        33.50       26.39  0.8489  1.1842
  16       0.730      0.680        27.73       22.18  0.8746  1.0598
  17       0.590      0.850        31.87       22.37  0.8570  1.4391
  18       0.630      0.660        31.07       24.77  0.8634  1.0837
  19       0.650      0.750        30.57       24.62  0.8650  1.1753
  20       0.570      0.720        31.21       26.92  0.9203  1.1229
coverage_before  mean 0.611  min 0.500  max 0.730
coverage_after   mean 0.725  min 0.650  max 0.850
mape_before      mean 31.389  min 26.750  max 38.330
mape_after       mean 25.212  min 21.220  max 30.210
coverage improved on 19/20 seeds; MAPE improved on 20/20 seeds
```

**Reading.** Calibration raised mean p10-p90 coverage on held-out data from 0.611 to 0.725 and lowered mean MAPE from
31.4 % to 25.2 %. MAPE improved on all 20 seeds and coverage on 19; on seed 16 coverage fell from 0.73 to 0.68.
Mean coverage after calibration (0.725) remains **below the 0.80 target**. Plausible reasons, not verified: the scale
is estimated from 100 outcomes with an approximately normal model of a log-normal process, and the bias is corrected
before the scale is fitted.

**Reproducibility.** The study is seeded and pure. Two runs in separate processes produced byte-identical output
(SHA-256 prefix `2eaa25466a73c025`), and `test_simulated_study_is_reproducible` checks it on every test run.

**Limits.** One synthetic crop, one noise model, a single prediction point per cycle, no weather or observation
effects. These numbers describe the calibration **method** under stated assumptions; they say nothing about accuracy
on real farms.

## Simulated harvest-pooling experiment (Phase 5, synthetic data)
`app/domain/pooling/experiment.py`; reproduce with `python -m app.cli.pooling_experiment`
(`--no-timing` for the deterministic part only).

**Question.** Does pooling uncertain supply from many farms with dynamic reallocation improve fulfilment and
robustness compared with static allocation, at comparable confidence? And does Harvestique's risk/confidence-aware
LP do better than a greedy baseline?

**Design.** Per seed and disruption level: 30 farms (predicted p50 ~ U(200, 600) kg, CV ~ U(0.10, 0.40),
p10/p90 = p50 (1 -/+ 1.2816 CV), risk = 150 CV, confidence = 100 - 120 CV, reliability ~ U(0.4, 0.9)); true yield =
p50 exp(N(0, CV) - CV^2/2); 4 competing pools each demanding 22% of total p10; a fraction of farms (0, 10, 25, 50%) is
disrupted (true yield x U(0.3, 0.7)); mid-season every prediction is revised towards the truth, triggering shortage
detection. **All strategies commit at p10** (comparable confidence). Strategies: **A** static (greedy allocation, never
rebalanced); **B** greedy allocation + greedy reallocation; **C** Harvestique risk/confidence-aware LP + LP
reallocation; **C0** ablation: C without the risk cap. The simulation calls the production domain functions
(`rank`, `greedy`, `lp`, `assign_shortfall`). 30 seeds x 4 levels x 4 strategies = 480 trials.

**Results (deterministic part; SHA-256 prefix `603994dc3e9fd679`, identical across runs).**
```
SIMULATED harvest-pooling experiment (synthetic data; not real-world performance)
30 seeds x 4 disruption levels x 4 strategies = 480 trials

level strategy             fulfil     sd  unres_kg atrisk/4 realloc_ok  steps alloc_eff  mape%  cover
  0.0 A_static             0.9929 0.0057     218.2     3.27        n/a    0.0    1.0000  19.99  0.823
  0.0 B_greedy             0.9992 0.0012       0.0     0.00      1.000   10.2    1.0000  19.99  0.823
  0.0 C_harvestique        0.9997 0.0007       0.0     0.00      1.000   18.8    1.0000  19.99  0.823
  0.0 C0_lp_no_risk_cap    0.9997 0.0007       0.0     0.00      1.000   18.7    1.0000  19.99  0.823
  0.1 A_static             0.9612 0.0167     494.7     3.50        n/a    0.0    1.0000  32.17  0.767
  0.1 B_greedy             0.9977 0.0040       0.0     0.00      1.000   13.8    1.0000  32.17  0.767
  0.1 C_harvestique        0.9881 0.0323      75.1     0.17      1.000   22.3    0.9890  32.17  0.767
  0.1 C0_lp_no_risk_cap    0.9985 0.0031       0.0     0.00      1.000   22.3    1.0000  32.17  0.767
 0.25 A_static             0.9001 0.0281    1011.2     4.00        n/a    0.0    1.0000  50.26  0.632
 0.25 B_greedy             0.9965 0.0036       0.0     0.00      1.000   21.0    1.0000  50.26  0.632
 0.25 C_harvestique        0.9917 0.0166      32.9     0.17      0.967   29.9    0.9976  50.26  0.632
 0.25 C0_lp_no_risk_cap    0.9967 0.0043       0.0     0.00      1.000   30.2    1.0000  50.26  0.632
  0.5 A_static             0.8351 0.0294    1564.3     4.00        n/a    0.0    1.0000  75.78  0.500
  0.5 B_greedy             0.9895 0.0154      38.8     0.20      0.950   29.3    1.0000  75.78  0.500
  0.5 C_harvestique        0.9656 0.0377     213.1     0.87      0.807   34.8    0.9956  75.78  0.500
  0.5 C0_lp_no_risk_cap    0.9902 0.0154      38.8     0.20      0.950   36.1    1.0000  75.78  0.500

Paired differences in fulfilment (same seed and world), mean and bootstrap 95% CI:
H1: pooling + dynamic reallocation beats static allocation
  level  0.0: +0.0068  [+0.0049, +0.0088]  supported
  level  0.1: +0.0269  [+0.0131, +0.0383]  supported
  level 0.25: +0.0916  [+0.0806, +0.1024]  supported
  level  0.5: +0.1305  [+0.1172, +0.1430]  supported
H1b: greedy reallocation beats static allocation
  level  0.0: +0.0063  [+0.0044, +0.0084]  supported
  level  0.1: +0.0364  [+0.0312, +0.0415]  supported
  level 0.25: +0.0964  [+0.0865, +0.1061]  supported
  level  0.5: +0.1544  [+0.1438, +0.1653]  supported
H2: risk/confidence-aware LP beats greedy
  level  0.0: +0.0005  [+0.0002, +0.0008]  supported
  level  0.1: -0.0095  [-0.0222, +0.0004]  no significant difference
  level 0.25: -0.0048  [-0.0110, +0.0002]  no significant difference
  level  0.5: -0.0239  [-0.0354, -0.0139]  rejected (worse)
Ablation: removing the LP risk cap
  level  0.0: +0.0000  [-0.0000, +0.0000]  no significant difference
  level  0.1: +0.0104  [+0.0008, +0.0229]  supported
  level 0.25: +0.0051  [+0.0002, +0.0113]  supported
  level  0.5: +0.0246  [+0.0147, +0.0358]  supported

```
```
Reallocation wall-clock time per trial, ms (machine-dependent, not reproducible):
  level  0.0: A_static=0.0  B_greedy=2.2  C_harvestique=18.5  C0_lp_no_risk_cap=18.4
  level  0.1: A_static=0.0  B_greedy=2.2  C_harvestique=20.6  C0_lp_no_risk_cap=19.7
  level 0.25: A_static=0.0  B_greedy=2.6  C_harvestique=22.7  C0_lp_no_risk_cap=22.8
  level  0.5: A_static=0.0  B_greedy=2.6  C_harvestique=22.5  C0_lp_no_risk_cap=22.8
```
Columns: fulfilment = delivered / demanded (true yields); unres_kg = planned shortage left after reallocation plus
over-commitment; atrisk/4 = pools at risk out of 4; realloc_ok = shortage events fully replaced / shortage events;
steps = allocation changes; alloc_eff = initially allocated / demanded; mape and cover = prediction error and p10-p90
coverage of the synthetic predictions (identical across strategies by construction).

**Findings.**
* **H1 supported at every disruption level:** pooling with dynamic reallocation (C) beats static allocation (A); the
  paired 95% CI excludes zero from +0.0068 (no disruption) to +0.1305 (50% of farms disrupted). Greedy reallocation
  (B) shows the same and slightly larger gains. Most of the benefit comes from **reallocating at all**.
* **H2 not supported:** the risk/confidence-aware LP is not better than greedy. It is indistinguishable at 10% and
  25% disruption and significantly **worse** at 50% (-0.0239, CI [-0.0354, -0.0139]), with more unresolved shortage
  (213 vs 39 kg) and more at-risk pools (0.87 vs 0.20 of 4).
* **The ablation explains why:** without the risk cap (C0) the LP matches greedy. The cap excludes high-CV farms that
  are still needed as replacements.
* **Important caveat:** in this world disruptions hit farms at random, independent of their risk score, so avoiding
  risky farms can only cost supply. Whether the cap pays off when risk *predicts* disruption has **not** been tested.
  The LP is also about 8-9x slower (about 20 ms vs 2.5 ms per trial on this machine).
* The synthetic predictions' coverage falls from 0.82 to 0.50 as disruption rises: disrupted farms fall outside their
  original ranges, which is why reallocation is needed.

**Limits.** One crop, one grade, identical windows, no distances, independent disruptions, a single mid-season
revision, synthetic risk scores. "Individual" sourcing (one farm per buyer) was not modelled separately: the static
baseline already spreads demand over farms but never adapts. These results describe the algorithms under these
assumptions only; there is no real-world pooling data.

## How real evaluation will work
Every recorded harvest creates feedback rows (error, % error, interval hit, pinball loss, date error per version) and
appends calibration profiles (`GET /calibration`). Once enough real outcomes exist, coverage, MAPE, pinball loss and
date error can be reported per crop from these tables.
