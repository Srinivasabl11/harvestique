"""ORM models.

Every model module must be imported here so Alembic autogenerate sees it.
"""

from app.models.auth import LoginAttempt, RefreshToken
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, VersionedMixin
from app.models.crop import Crop, CropCycle
from app.models.engagement import CropHealthAnalysis, Notification, Reminder
from app.models.farm import Farm, FarmPlot
from app.models.farm_records import CropObservation, FarmActivity, FarmExpense
from app.models.intelligence import (
    CalibrationProfile,
    HarvestActual,
    InventoryLot,
    InventoryReservation,
    MarketPrice,
    PredictionFeedback,
    ProduceGrading,
    WeatherDaily,
    YieldPrediction,
)
from app.models.marketplace import (
    BuyerOrder,
    BuyerOrderItem,
    CollectionHub,
    FarmerParticipation,
    ProduceBatch,
    QualityCheck,
)
from app.models.planning import CropPlan, CropPlanItem
from app.models.pooling import (
    AllocationLedger,
    BuyerDemand,
    HarvestAllocation,
    HarvestPool,
    HarvestPoolMember,
    ReallocationEvent,
)
from app.models.profiles import BuyerProfile, FarmerProfile
from app.models.user import User

__all__ = [
    "AllocationLedger",
    "Base",
    "BuyerDemand",
    "BuyerOrder",
    "BuyerOrderItem",
    "BuyerProfile",
    "CalibrationProfile",
    "CollectionHub",
    "Crop",
    "CropCycle",
    "CropHealthAnalysis",
    "CropObservation",
    "CropPlan",
    "CropPlanItem",
    "Farm",
    "FarmActivity",
    "FarmExpense",
    "FarmPlot",
    "FarmerParticipation",
    "FarmerProfile",
    "HarvestActual",
    "HarvestAllocation",
    "HarvestPool",
    "HarvestPoolMember",
    "InventoryLot",
    "InventoryReservation",
    "LoginAttempt",
    "MarketPrice",
    "Notification",
    "PredictionFeedback",
    "ProduceBatch",
    "ProduceGrading",
    "QualityCheck",
    "ReallocationEvent",
    "RefreshToken",
    "Reminder",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "User",
    "VersionedMixin",
    "WeatherDaily",
    "YieldPrediction",
]
