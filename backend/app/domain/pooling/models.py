"""Value objects for Dynamic Predictive Harvest Pooling (pure)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.core.enums import QualityGrade

D = Decimal
ZERO = D(0)
KG = D("0.001")
HUNDRED = D(100)
_W_CONFIDENCE, _W_SAFETY, _W_RELIABILITY = D("0.25"), D("0.20"), D("0.15")
_W_WINDOW, _W_PROXIMITY, _W_AVAILABILITY = D("0.15"), D("0.10"), D("0.15")


@dataclass(frozen=True, slots=True)
class Weights:
    """Allocation score weights (configurable per pool; must sum to 1)."""

    confidence: Decimal = _W_CONFIDENCE
    safety: Decimal = _W_SAFETY  # 100 - risk
    reliability: Decimal = _W_RELIABILITY
    window: Decimal = _W_WINDOW
    proximity: Decimal = _W_PROXIMITY
    availability: Decimal = _W_AVAILABILITY

    def __post_init__(self) -> None:
        values = [self.confidence, self.safety, self.reliability, self.window, self.proximity, self.availability]
        if any(v < 0 for v in values) or sum(values) != 1:
            raise ValueError("weights must be non-negative and sum to 1")


@dataclass(frozen=True, slots=True)
class Supply:
    """One farm's uncertain future supply (an inventory lot) as seen by the pooling engine."""

    lot_id: str
    farm_ref: str
    crop_id: str
    grade: QualityGrade
    available_kg: Decimal  # p10-based committable minus existing commitments (Phase 4 inventory)
    p50_kg: Decimal | None
    window_start: date
    window_end: date
    confidence: Decimal  # 0-100, latest prediction
    risk: Decimal | None  # 0-100, latest prediction overall risk (None = not assessed)
    reliability: Decimal  # 0-1, from recorded prediction outcomes (0.5 when none)
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    opted_in: bool = True
    lot_open: bool = True


@dataclass(frozen=True, slots=True)
class DemandSpec:
    crop_id: str
    quantity_kg: Decimal
    window_start: date
    window_end: date
    min_grade: QualityGrade = QualityGrade.C
    min_confidence: Decimal = ZERO
    max_risk: Decimal = HUNDRED
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    max_distance_km: Decimal | None = None


@dataclass(frozen=True, slots=True)
class Match:
    supply: Supply
    eligible: bool
    reasons: tuple[str, ...]
    score: Decimal
    components: dict[str, Decimal] = field(default_factory=dict)
    distance_km: Decimal | None = None


@dataclass(frozen=True, slots=True)
class MatchSummary:
    """Can the demand be met from current predicted supply? Deterministic arithmetic, no AI."""

    fulfilment: str  # full / partial / none
    need_kg: Decimal
    eligible_kg: Decimal  # sum of eligible lots' available (p10-based) quantity
    shortage_kg: Decimal  # need - eligible, never negative
    eligible_count: int
    excluded: dict[str, int]  # ineligibility reason -> number of lots with it
    explanation: tuple[str, ...]
    next_steps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlanLine:
    lot_id: str
    quantity_kg: Decimal
    score: Decimal


@dataclass(frozen=True, slots=True)
class Plan:
    lines: tuple[PlanLine, ...]
    total_kg: Decimal
    algorithm: str
    notes: tuple[str, ...]
