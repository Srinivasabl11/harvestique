"""Reproduce the SIMULATED pooling experiment reported in docs/EVALUATION.md.

    python -m app.cli.pooling_experiment              # 30 seeds x 4 disruption levels x 4 strategies
    python -m app.cli.pooling_experiment --no-timing  # deterministic output only (for reproducibility checks)

All data is synthetic. Results describe the algorithms under stated assumptions, not real-world performance.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from statistics import mean, pstdev

from app.domain.pooling.experiment import STRATEGIES, TrialResult, bootstrap_ci, run

SEEDS = tuple(range(1, 31))
LEVELS = (0.0, 0.1, 0.25, 0.5)
COMPARISONS = (
    ("C_harvestique", "A_static", "H1: pooling + dynamic reallocation beats static allocation"),
    ("B_greedy", "A_static", "H1b: greedy reallocation beats static allocation"),
    ("C_harvestique", "B_greedy", "H2: risk/confidence-aware LP beats greedy"),
    ("C0_lp_no_risk_cap", "C_harvestique", "Ablation: removing the LP risk cap"),
)


def _cell(rows: Sequence[TrialResult]) -> dict[str, float]:
    events = sum(r.shortage_events for r in rows)
    return {
        "fulfilment": mean(r.fulfilment for r in rows),
        "fulfilment_sd": pstdev(r.fulfilment for r in rows),
        "unresolved_kg": mean(r.unresolved_shortage_kg for r in rows),
        "at_risk_pools": mean(r.at_risk_pools for r in rows),
        "realloc_success": (sum(r.resolved_events for r in rows) / events) if events else float("nan"),
        "steps": mean(r.reallocation_steps for r in rows),
        "efficiency": mean(r.allocation_efficiency for r in rows),
        "mape": mean(r.mape for r in rows),
        "coverage": mean(r.coverage for r in rows),
        "ms": mean(r.reallocation_ms for r in rows),
    }


def main(argv: Sequence[str] | None = None) -> int:
    timing = "--no-timing" not in (argv or [])
    results = run(SEEDS, LEVELS)
    print("SIMULATED harvest-pooling experiment (synthetic data; not real-world performance)")
    print(
        f"{len(SEEDS)} seeds x {len(LEVELS)} disruption levels x {len(STRATEGIES)} strategies = {len(results)} trials\n"
    )
    print(
        f"{'level':>5} {'strategy':<19} {'fulfil':>7} {'sd':>6} {'unres_kg':>9} {'atrisk/4':>8} {'realloc_ok':>10} {'steps':>6} {'alloc_eff':>9} {'mape%':>6} {'cover':>6}"
    )
    cells = {}
    for lvl in LEVELS:
        for s in STRATEGIES:
            c = _cell([r for r in results if r.level == lvl and r.strategy == s])
            cells[(lvl, s)] = c
            ok = "n/a" if c["realloc_success"] != c["realloc_success"] else f"{c['realloc_success']:.3f}"
            print(
                f"{lvl:>5} {s:<19} {c['fulfilment']:7.4f} {c['fulfilment_sd']:6.4f} {c['unresolved_kg']:9.1f} {c['at_risk_pools']:8.2f} {ok:>10} {c['steps']:6.1f} {c['efficiency']:9.4f} {c['mape']:6.2f} {c['coverage']:6.3f}"
            )
    print("\nPaired differences in fulfilment (same seed and world), mean and bootstrap 95% CI:")
    for a, b, label in COMPARISONS:
        print(label)
        for lvl in LEVELS:
            fa = {r.seed: r.fulfilment for r in results if r.level == lvl and r.strategy == a}
            fb = {r.seed: r.fulfilment for r in results if r.level == lvl and r.strategy == b}
            m, lo, hi = bootstrap_ci([fa[s] - fb[s] for s in SEEDS])
            verdict = "supported" if lo > 0 else "rejected (worse)" if hi < 0 else "no significant difference"
            print(f"  level {lvl:>4}: {m:+.4f}  [{lo:+.4f}, {hi:+.4f}]  {verdict}")
    if timing:
        print("\nReallocation wall-clock time per trial, ms (machine-dependent, not reproducible):")
        for lvl in LEVELS:
            print(f"  level {lvl:>4}: " + "  ".join(f"{s}={cells[(lvl, s)]['ms']:.1f}" for s in STRATEGIES))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
