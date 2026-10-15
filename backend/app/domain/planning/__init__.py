"""Farm income and land planning engine (pure domain logic).

evaluate_plan(PlanInput)      -> PlanResult        cost, yield/revenue ranges, margin, break-even,
                                                   land use, income continuity, risk, confidence
suggest_allocation(Allocation) -> AllocationOutput  deterministic greedy split of land between crops
"""

from app.domain.planning.allocation import (
    Allocation,
    AllocationInput,
    AllocationOutput,
    Candidate,
    Excluded,
    suggest_allocation,
)
from app.domain.planning.engine import ASSUMPTIONS, DISCLAIMER, evaluate_plan
from app.domain.planning.models import (
    CostInputs,
    ItemInput,
    PlanInput,
    PlanningInputError,
    PlanResult,
    Range,
)

__all__ = [
    "ASSUMPTIONS",
    "DISCLAIMER",
    "Allocation",
    "AllocationInput",
    "AllocationOutput",
    "Candidate",
    "CostInputs",
    "Excluded",
    "ItemInput",
    "PlanInput",
    "PlanResult",
    "PlanningInputError",
    "Range",
    "evaluate_plan",
    "suggest_allocation",
]
