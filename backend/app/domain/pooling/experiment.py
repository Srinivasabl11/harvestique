"""SIMULATED research experiment: does pooling + dynamic reallocation improve fulfilment and robustness?

All data here is SYNTHETIC (seeded). The experiment reuses the real domain algorithms (matching.rank,
optimizer.greedy / optimizer.lp, shortage.assign_shortfall); nothing is re-implemented for the simulation.

World (per seed and disruption level):
  * 30 farms of one crop. Each has a predicted p50 ~ U(200, 600) kg and an uncertainty CV ~ U(0.10, 0.40);
    p10/p90 = p50 (1 -/+ 1.2816 CV) as in the Phase 4 model. Prediction risk = 150 x CV (as the Phase 4 yield
    risk); confidence = 100 - 120 x CV; reliability ~ U(0.4, 0.9).
  * True yield = p50 x exp(N(0, CV) - CV^2/2)  (unbiased on average, CV-dependent spread).
  * 4 competing pools, each demanding 22% of total farm p10 (88% of p10 supply in total).
  * Disruption: a fraction `level` of farms suffers an event that cuts the true yield by U(30%, 70%).
  * Mid-season every farm's prediction is revised: p50' = true x exp(N(0, CV/2)), with the revised spread
    halved; that revision is what triggers shortage detection and reallocation.
Strategies (ALL commit at p10, i.e. comparable confidence):
  A  static : greedy initial allocation, never rebalanced
  B  greedy : greedy initial allocation + greedy reallocation of every detected shortage
  C  harvestique : risk/confidence-aware LP allocation + LP reallocation
  C0 ablation    : the same LP with the average-risk constraint switched off (isolates its effect)
Delivery: each farm's TRUE yield is shared among its allocations in proportion to their size.
"""

from __future__ import annotations

import math
import random
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from statistics import mean

from app.core.enums import QualityGrade
from app.domain.pooling.matching import rank
from app.domain.pooling.models import D, DemandSpec, Supply, Weights
from app.domain.pooling.optimizer import allocate
from app.domain.pooling.shortage import Commitment, assign_shortfall

Z = 1.2816
STRATEGIES = ("A_static", "B_greedy", "C_harvestique", "C0_lp_no_risk_cap")
WINDOW = (date(2027, 1, 1), date(2027, 1, 31))


@dataclass
class Farm:
    ref: str
    p10: float
    p50: float
    p90: float
    cv: float
    true: float
    reliability: float
    revised_p10: float = 0.0


@dataclass(frozen=True)
class TrialResult:
    strategy: str
    level: float
    seed: int
    fulfilment: float  # delivered / demanded (true yields)
    unresolved_shortage_kg: float  # planned shortage left after reallocation
    at_risk_pools: int
    shortage_events: int
    resolved_events: int
    reallocation_steps: int
    reallocation_ms: float  # wall clock: machine-dependent, excluded from reproducibility checks
    allocation_efficiency: float  # initially allocated / demanded
    mape: float  # initial p50 vs truth
    coverage: float  # share of truths inside initial p10-p90


def _world(seed: int, level: float, n_farms: int = 30) -> tuple[list[Farm], list[float]]:
    rng = random.Random(seed * 1000 + int(level * 100))  # noqa: S311 - reproducible synthetic data
    farms = []
    for i in range(n_farms):
        p50 = rng.uniform(200, 600)
        cv = rng.uniform(0.10, 0.40)
        true = p50 * math.exp(rng.gauss(0, cv) - cv * cv / 2)
        farms.append(
            Farm(f"F{i:02d}", max(0.0, p50 * (1 - Z * cv)), p50, p50 * (1 + Z * cv), cv, true, rng.uniform(0.4, 0.9))
        )
    for f in rng.sample(farms, round(level * n_farms)):
        f.true *= rng.uniform(0.3, 0.7)
    for f in farms:
        revised_p50 = f.true * math.exp(rng.gauss(0, f.cv / 2))
        f.revised_p10 = max(0.0, revised_p50 * (1 - Z * f.cv / 2))
    total_p10 = sum(f.p10 for f in farms)
    return farms, [0.22 * total_p10] * 4


def _supplies(farms: Sequence[Farm], available: dict[str, float], conf_from_cv: bool = True) -> list[Supply]:
    return [
        Supply(
            lot_id=f.ref,
            farm_ref=f.ref,
            crop_id="crop",
            grade=QualityGrade.B,
            available_kg=D(str(round(max(0.0, available[f.ref]), 3))),
            p50_kg=D(str(round(f.p50, 3))),
            window_start=WINDOW[0],
            window_end=WINDOW[1],
            confidence=D(str(round(max(0.0, 100 - 120 * f.cv), 1))),
            risk=D(str(round(min(100.0, 150 * f.cv), 1))),
            reliability=D(str(round(f.reliability, 3))),
        )
        for f in farms
    ]


def _allocate(
    algorithm: str, farms: Sequence[Farm], available: dict[str, float], need: float, max_risk: Decimal
) -> dict[str, float]:
    demand = DemandSpec("crop", D(str(round(need, 3))), *WINDOW)
    plan = allocate(
        algorithm,
        rank(_supplies(farms, available), demand, demand.quantity_kg, Weights()),
        demand.quantity_kg,
        max_pool_risk=max_risk,
    )
    return {ln.lot_id: float(ln.quantity_kg) for ln in plan.lines}


def run_trial(strategy: str, seed: int, level: float) -> TrialResult:
    farms, demands = _world(seed, level)
    algorithm = "lp" if strategy.startswith("C") else "greedy"
    max_risk = D(100) if strategy == "C0_lp_no_risk_cap" else D(50)
    available = {f.ref: f.p10 for f in farms}
    allocs: list[dict[str, float]] = []
    order: dict[tuple[int, str], int] = {}
    seq = 0
    for k, need in enumerate(demands):
        a = _allocate(algorithm, farms, available, need, max_risk)
        for ref, q in a.items():
            available[ref] -= q
            seq += 1
            order[(k, ref)] = seq
        allocs.append(a)
    initially = sum(sum(a.values()) for a in allocs)

    events = resolved = steps = 0
    elapsed = 0.0
    if strategy != "A_static":
        t0 = time.perf_counter()
        # 1-3. detect each farm's exact shortfall after revision and cut the newest pool commitments first
        cut_by_pool = [0.0] * len(demands)
        for f in farms:
            commits = [
                Commitment(f"{k}:{f.ref}", D(str(round(a[f.ref], 3))), order[(k, f.ref)], True)
                for k, a in enumerate(allocs)
                if f.ref in a
            ]
            committed = sum(float(c.quantity_kg) for c in commits)
            shortfall = max(0.0, committed - f.revised_p10)
            available[f.ref] = max(0.0, f.revised_p10 - committed)
            if shortfall <= 0:
                continue
            assignment = assign_shortfall(D(str(round(shortfall, 3))), commits)
            for rid, cut_kg in assignment.cuts.items():
                k = int(rid.split(":")[0])
                allocs[k][f.ref] -= float(cut_kg)
                cut_by_pool[k] += float(cut_kg)
                steps += 1
        # 4-7. replace from eligible remaining supply, pool by pool
        for k, lost in enumerate(cut_by_pool):
            if lost <= 0:
                continue
            events += 1
            replacement = _allocate(algorithm, farms, available, lost, max_risk)
            got = sum(replacement.values())
            for ref, q in replacement.items():
                allocs[k][ref] = allocs[k].get(ref, 0.0) + q
                available[ref] -= q
                steps += 1
            resolved += int(got >= lost - 0.01)
        elapsed = (time.perf_counter() - t0) * 1000

    planned_short = [max(0.0, d - sum(a.values())) for d, a in zip(demands, allocs, strict=True)]
    # an at-risk pool is one whose commitments now exceed what the (revised) predictions can cover
    exposure = [0.0] * len(demands)
    for f in farms:
        committed = sum(a.get(f.ref, 0.0) for a in allocs)
        if committed > f.revised_p10 + 0.01:
            for k, a in enumerate(allocs):
                if f.ref in a:
                    exposure[k] += a[f.ref] / committed * (committed - f.revised_p10)
    at_risk = sum(1 for s, e in zip(planned_short, exposure, strict=True) if s > 0.01 or e > 0.01)
    delivered = 0.0
    for f in farms:
        committed = sum(a.get(f.ref, 0.0) for a in allocs)
        delivered += min(committed, f.true)
    return TrialResult(
        strategy,
        level,
        seed,
        fulfilment=delivered / sum(demands),
        unresolved_shortage_kg=sum(planned_short) + sum(exposure),
        at_risk_pools=at_risk,
        shortage_events=events,
        resolved_events=resolved,
        reallocation_steps=steps,
        reallocation_ms=elapsed,
        allocation_efficiency=initially / sum(demands),
        mape=mean(abs(f.true - f.p50) / f.true * 100 for f in farms if f.true > 0),
        coverage=mean(1.0 if f.p10 <= f.true <= f.p90 else 0.0 for f in farms),
    )


def bootstrap_ci(diffs: Sequence[float], seed: int = 12345, n: int = 2000) -> tuple[float, float, float]:
    rng = random.Random(seed)  # noqa: S311
    means = sorted(mean(rng.choice(diffs) for _ in diffs) for _ in range(n))
    return mean(diffs), means[int(0.025 * n)], means[int(0.975 * n) - 1]


def run(
    seeds: Sequence[int] = tuple(range(1, 31)), levels: Sequence[float] = (0.0, 0.1, 0.25, 0.5)
) -> list[TrialResult]:
    return [run_trial(s, seed, lvl) for lvl in levels for seed in seeds for s in STRATEGIES]
