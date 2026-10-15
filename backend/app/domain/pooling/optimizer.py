"""Allocation algorithms: a greedy baseline and Harvestique's staged LP (HiGHS via SciPy).

Both only ever allocate up to each lot's `available_kg` (p10-based, net of existing commitments), never more
than the requested need, and return quantities floored to whole grams, so supply can never be over-committed.

LP (risk/confidence-aware), all linear:
  stage 1  T1 = max sum(x)     s.t. sum(x) <= need, 0 <= x_i <= avail_i, sum((risk_i - R) x_i) <= 0
  stage 2  T2 = same + x_i <= cap * need (diversification); the cap is kept only if T2 == T1 (never costs fulfilment)
  stage 3  max sum(score_i x_i) s.t. sum(x) = T (T from stage 1/2) and the same constraints
R = maximum average pool risk; unassessed risk counts as 50.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_FLOOR, Decimal

import numpy as np
from scipy.optimize import linprog

from app.domain.pooling.models import KG, ZERO, D, Match, Plan, PlanLine

DEFAULT_MAX_POOL_RISK = D(50)
DEFAULT_MAX_SHARE = D("0.4")
_EPS = 1e-6


def _floor(x: float | Decimal) -> Decimal:
    return D(str(x)).quantize(KG, rounding=ROUND_FLOOR)


def _risk(m: Match) -> Decimal:
    return D(50) if m.supply.risk is None else m.supply.risk


def greedy(matches: Sequence[Match], need_kg: Decimal) -> Plan:
    remaining, lines = need_kg, []
    for m in matches:
        if not m.eligible or remaining <= 0:
            continue
        take = min(m.supply.available_kg, remaining).quantize(KG, rounding=ROUND_FLOOR)
        if take > 0:
            lines.append(PlanLine(m.supply.lot_id, take, m.score))
            remaining -= take
    return Plan(
        tuple(lines), need_kg - remaining, "greedy", ("Highest score first; no risk or diversification constraints.",)
    )


def lp(
    matches: Sequence[Match],
    need_kg: Decimal,
    *,
    max_pool_risk: Decimal = DEFAULT_MAX_POOL_RISK,
    max_share: Decimal = DEFAULT_MAX_SHARE,
) -> Plan:
    cands = [m for m in matches if m.eligible and m.supply.available_kg > 0]
    if not cands or need_kg <= 0:
        return Plan((), ZERO, "lp", ("No eligible supply.",))
    n = len(cands)
    avail = np.array([float(m.supply.available_kg) for m in cands])
    risk = np.array([float(_risk(m) - max_pool_risk) for m in cands])
    score = np.array([float(m.score) for m in cands])
    need = float(need_kg)
    a_ub = np.vstack([np.ones(n), risk])
    b_ub = np.array([need, 0.0])

    def solve(c: np.ndarray, upper: np.ndarray, total: float | None = None) -> np.ndarray | None:
        a_eq, b_eq = (np.ones((1, n)), np.array([total])) if total is not None else (None, None)
        res = linprog(
            c,
            A_ub=a_ub,
            b_ub=b_ub,
            A_eq=a_eq,
            b_eq=b_eq,
            bounds=list(zip([0.0] * n, upper, strict=True)),
            method="highs",
        )
        return res.x if res.status == 0 else None

    notes = [f"Average pool risk kept <= {max_pool_risk} (unassessed risk counts as 50)."]
    x1 = solve(-np.ones(n), avail)
    if x1 is None:
        return Plan((), ZERO, "lp", ("LP infeasible.",))
    t1 = float(x1.sum())
    capped = np.minimum(avail, float(max_share) * need)
    x2 = solve(-np.ones(n), capped)
    use_cap = x2 is not None and float(x2.sum()) >= t1 - 1e-3
    upper = capped if use_cap else avail
    notes.append(
        f"Diversification cap {int(max_share * 100)}% per farm "
        + ("applied." if use_cap else "relaxed: it would have reduced fulfilment.")
    )
    total = t1 if not use_cap else float(x2.sum())  # type: ignore[union-attr]
    x3 = solve(-score, upper, max(0.0, total - _EPS))
    x = x3 if x3 is not None else (x2 if use_cap else x1)
    assert x is not None

    lines: list[PlanLine] = []
    for m, v, hi in zip(cands, x, upper, strict=True):
        q = min(_floor(max(0.0, float(v))), m.supply.available_kg, _floor(hi))
        if q > 0:
            lines.append(PlanLine(m.supply.lot_id, q, m.score))
    # Flooring can leave a few grams; top up within limits from the lowest-risk lines (never past availability).
    allocated = sum((ln.quantity_kg for ln in lines), ZERO)
    gap = min(need_kg, _floor(total)) - allocated
    if gap > 0:
        by_lot = {ln.lot_id: ln for ln in lines}
        for m in sorted(cands, key=lambda m: (_risk(m), m.supply.lot_id)):
            if gap <= 0:
                break
            ln = by_lot.get(m.supply.lot_id)
            cur = ln.quantity_kg if ln else ZERO
            room = min(m.supply.available_kg, _floor(upper[cands.index(m)])) - cur
            add = min(room, gap)
            if add > 0 and _risk(m) <= max_pool_risk:
                by_lot[m.supply.lot_id] = PlanLine(m.supply.lot_id, cur + add, m.score)
                gap -= add
        lines = sorted(by_lot.values(), key=lambda ln: (-ln.score, ln.lot_id))
    return Plan(tuple(lines), sum((ln.quantity_kg for ln in lines), ZERO), "lp", tuple(notes))


def allocate(
    algorithm: str,
    matches: Sequence[Match],
    need_kg: Decimal,
    *,
    max_pool_risk: Decimal = DEFAULT_MAX_POOL_RISK,
    max_share: Decimal = DEFAULT_MAX_SHARE,
) -> Plan:
    if algorithm == "greedy":
        return greedy(matches, need_kg)
    return lp(matches, need_kg, max_pool_risk=max_pool_risk, max_share=max_share)
