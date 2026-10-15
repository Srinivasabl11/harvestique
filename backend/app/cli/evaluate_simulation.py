"""Reproduce the SIMULATED calibration study reported in docs/EVALUATION.md.

    python -m app.cli.evaluate_simulation            # seeds 1..20, 200 synthetic cycles each

Synthetic data only: the output describes the calibration METHOD, not real-world accuracy.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from statistics import mean

from app.domain.prediction.simulation import StudyResult, run_study


def study(seeds: Sequence[int]) -> list[StudyResult]:
    return [run_study(s) for s in seeds]


def summary(results: Sequence[StudyResult]) -> dict[str, tuple[float, float, float]]:
    out: dict[str, tuple[float, float, float]] = {}
    for key in ("coverage_before", "coverage_after", "mape_before", "mape_after"):
        values = [float(getattr(r, key)) for r in results]
        out[key] = (round(mean(values), 3), min(values), max(values))
    return out


def main(argv: Sequence[str] | None = None) -> int:
    results = study(range(1, 21))
    print("SIMULATED calibration study (synthetic data; not real-world accuracy)")
    print("seed  cov_before  cov_after  mape_before  mape_after  bias   scale")
    for r in results:
        row = (
            r.seed,
            r.coverage_before,
            r.coverage_after,
            r.mape_before,
            r.mape_after,
            r.bias_factor,
            r.interval_scale,
        )
        print("{:>4}  {:>10}  {:>9}  {:>11}  {:>10}  {}  {}".format(*row))
    for key, (avg, lo, hi) in summary(results).items():
        print(f"{key:16s} mean {avg:.3f}  min {lo:.3f}  max {hi:.3f}")
    improved_cov = sum(r.coverage_after > r.coverage_before for r in results)
    improved_mape = sum(r.mape_after < r.mape_before for r in results)
    print(f"coverage improved on {improved_cov}/20 seeds; MAPE improved on {improved_mape}/20 seeds")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
