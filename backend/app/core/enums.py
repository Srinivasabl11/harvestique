"""Shared enumerations (no framework imports so any layer may use them)."""

from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    FARMER = "farmer"
    BUYER = "buyer"
    ADMIN = "admin"


class OtpPurpose(StrEnum):
    REGISTER = "register"
    LOGIN = "login"
    PASSWORD_RESET = "password_reset"  # noqa: S105 - an OTP purpose, not a secret


class PreferredLanguage(StrEnum):
    ENGLISH = "en"
    KANNADA = "kn"


class BuyerType(StrEnum):
    RETAILER = "retailer"
    WHOLESALER = "wholesaler"
    PROCESSOR = "processor"
    RESTAURANT = "restaurant"
    OTHER = "other"


# ---------------------------------------------------------------- farming


class SoilType(StrEnum):
    RED = "red"
    BLACK = "black"
    ALLUVIAL = "alluvial"
    LATERITE = "laterite"
    SANDY = "sandy"
    LOAMY = "loamy"
    CLAY = "clay"
    OTHER = "other"


class IrrigationType(StrEnum):
    RAINFED = "rainfed"
    BOREWELL = "borewell"
    CANAL = "canal"
    DRIP = "drip"
    SPRINKLER = "sprinkler"
    TANK = "tank"
    RIVER = "river"
    OTHER = "other"


class CropCategory(StrEnum):
    VEGETABLE = "vegetable"
    FRUIT = "fruit"
    CEREAL = "cereal"
    PULSE = "pulse"
    OILSEED = "oilseed"
    SPICE = "spice"
    CASH_CROP = "cash_crop"
    PLANTATION = "plantation"
    FLOWER = "flower"
    FODDER = "fodder"
    MEDICINAL = "medicinal"
    OTHER = "other"


class CropGroup(StrEnum):
    """Agricultural group (finer than the category; see app/domain/crop_catalog.GROUPS)."""

    CEREALS = "cereals"
    MILLETS = "millets"
    PULSES = "pulses"
    OILSEEDS = "oilseeds"
    VEGETABLES = "vegetables"
    FRUITS = "fruits"
    SPICES = "spices"
    ROOTS_TUBERS = "roots_tubers"
    PLANTATION = "plantation"
    BEVERAGE = "beverage"
    FIBRE = "fibre"
    SUGAR_STARCH = "sugar_starch"
    FODDER = "fodder"
    MEDICINAL_AROMATIC = "medicinal_aromatic"
    ORNAMENTAL = "ornamental"
    AGROFORESTRY = "agroforestry"
    MUSHROOMS = "mushrooms"
    OTHER = "other"


class CropSeason(StrEnum):
    KHARIF = "kharif"
    RABI = "rabi"
    SUMMER = "summer"
    YEAR_ROUND = "year_round"


class CycleStatus(StrEnum):
    PLANNED = "planned"
    GROWING = "growing"
    HARVESTED = "harvested"
    ABANDONED = "abandoned"


class ExpenseCategory(StrEnum):
    SEED = "seed"
    FERTILIZER = "fertilizer"
    PESTICIDE = "pesticide"
    LABOUR = "labour"
    IRRIGATION = "irrigation"
    MACHINERY = "machinery"
    TRANSPORT = "transport"
    OTHER = "other"


class ActivityType(StrEnum):
    LAND_PREPARATION = "land_preparation"
    SOWING = "sowing"
    IRRIGATION = "irrigation"
    FERTILIZING = "fertilizing"
    PEST_CONTROL = "pest_control"
    WEEDING = "weeding"
    PRUNING = "pruning"
    HARVESTING = "harvesting"
    OTHER = "other"


class GrowthStage(StrEnum):
    GERMINATION = "germination"
    VEGETATIVE = "vegetative"
    FLOWERING = "flowering"
    FRUITING = "fruiting"
    MATURITY = "maturity"


class HealthStatus(StrEnum):
    HEALTHY = "healthy"
    STRESSED = "stressed"
    PEST_AFFECTED = "pest_affected"
    DISEASE_AFFECTED = "disease_affected"
    DAMAGED = "damaged"


# ---------------------------------------------------------------- planning


class DemandLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ConfidenceLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EstimateBasis(StrEnum):
    """Where the farmer's yield/price numbers come from (drives the confidence score)."""

    OWN_RECORDS = "own_records"
    LOCAL_KNOWLEDGE = "local_knowledge"
    ASSUMPTION = "assumption"


class RankBy(StrEnum):
    MARGIN_PER_ACRE = "margin_per_acre"
    RETURN_ON_COST = "return_on_cost"


class FindingSeverity(StrEnum):
    HARD = "hard"  # the plan is not feasible as entered
    WARNING = "warning"  # feasible, but worth attention


class ContinuityLevel(StrEnum):
    CONTINUOUS = "continuous"
    UNEVEN = "uneven"
    GAPPED = "gapped"
    SINGLE_HARVEST = "single_harvest"


# ------------------------------------------------------------ intelligence


class DataKind(StrEnum):
    """Provenance of every number the intelligence layer uses or produces."""

    MEASURED = "measured"  # observed: reanalysis weather, farmer-recorded observations, recorded harvests
    ESTIMATE = "estimate"  # forecasts, farmer estimates, model outputs
    ASSUMPTION = "assumption"  # reference/default values not specific to this farm
    SIMULATED = "simulated"  # synthetic data (evaluation studies only)


class WeatherKind(StrEnum):
    OBSERVED = "observed"
    FORECAST = "forecast"


class WeatherStatus(StrEnum):
    FRESH = "fresh"
    STALE = "stale"  # served from cache after a failed or skipped refresh
    UNAVAILABLE = "unavailable"


class PredictionStatus(StrEnum):
    OK = "ok"
    INSUFFICIENT_DATA = "insufficient_data"


class RiskCategory(StrEnum):
    WEATHER = "weather"
    DISEASE = "disease"
    WATER = "water"
    YIELD = "yield"
    MARKET = "market"
    DEMAND = "demand"
    LABOUR = "labour"
    TIMING = "timing"
    FULFILMENT = "fulfilment"


class LotStatus(StrEnum):
    OPEN = "open"  # predicted, pre-harvest
    AT_RISK = "at_risk"  # commitments exceed what can be safely promised
    HARVESTED = "harvested"
    CANCELLED = "cancelled"  # crop cycle abandoned


class ReservationStatus(StrEnum):
    ACTIVE = "active"
    RELEASED = "released"
    FULFILLED = "fulfilled"


# ----------------------------------------------------------------- pooling


class QualityGrade(StrEnum):
    A = "A"  # best
    B = "B"
    C = "C"


class DemandStatus(StrEnum):
    OPEN = "open"
    POOLED = "pooled"
    CANCELLED = "cancelled"


class PoolStatus(StrEnum):
    FILLED = "filled"  # allocated == demand, no affected supply
    PARTIAL = "partial"  # created short because supply was insufficient
    AT_RISK = "at_risk"  # a supply drop left an unresolved shortage
    UNFILLED = "unfilled"  # nothing could be allocated


class AllocationStatus(StrEnum):
    ACTIVE = "active"
    REDUCED = "reduced"  # cut by a supply drop, still > 0
    RELEASED = "released"  # cut to 0
    FULFILLED = "fulfilled"


class PoolAlgorithm(StrEnum):
    GREEDY = "greedy"  # default: greedy + dynamic reallocation (best in the simulated evaluation)
    LP = "lp"  # research: risk/confidence-aware staged LP (did not outperform greedy)


class ReallocationOutcome(StrEnum):
    NO_CHANGE = "no_change"
    FULL = "full"
    PARTIAL = "partial"
    NONE = "none"
    TOP_UP = "top_up"  # no shortage; unfilled need was (partly) filled


# ------------------------------------------------------------ marketplace


class OrderStatus(StrEnum):
    PLACED = "placed"  # farmers asked to confirm
    CONFIRMED = "confirmed"  # every open item accepted by its farmer
    IN_FULFILMENT = "in_fulfilment"  # produce being collected / checked
    FULFILLED = "fulfilled"  # delivered quantity reached the ordered quantity
    PARTIALLY_FULFILLED = "partially_fulfilled"  # all items closed, total below the ordered quantity
    CANCELLED = "cancelled"


class OrderItemStatus(StrEnum):
    AWAITING_FARMER = "awaiting_farmer"
    ACCEPTED = "accepted"
    DECLINED = "declined"  # supply released; replacement attempted by reallocation
    REMOVED = "removed"  # allocation cut to 0 by reallocation
    FULFILLED = "fulfilled"
    SHORT = "short"  # closed with nothing accepted
    CANCELLED = "cancelled"


class ParticipationStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    WITHDRAWN = "withdrawn"  # allocation removed by the system


class FarmerProgress(StrEnum):
    """The farmer's own progress on an accepted supply request (shown to the buyer)."""

    PREPARING = "preparing"
    READY = "ready"


class BatchStatus(StrEnum):
    RECEIVED = "received"
    QUALITY_CHECKED = "quality_checked"
    CLOSED = "closed"  # counted towards fulfilment


class QualityResult(StrEnum):
    ACCEPTED = "accepted"
    PARTIALLY_ACCEPTED = "partially_accepted"
    REJECTED = "rejected"


class ReminderType(StrEnum):
    CROP_OBSERVATION = "crop_observation"
    IRRIGATION = "irrigation"
    ACTIVITY = "activity"
    CROP_HEALTH = "crop_health"
    HARVEST = "harvest"
    BUYER_OPPORTUNITY = "buyer_opportunity"
    COLLECTION = "collection"
    EXPENSE = "expense"
    CUSTOM = "custom"


class ReminderStatus(StrEnum):
    PENDING = "pending"
    DONE = "done"
    DISMISSED = "dismissed"


class Recurrence(StrEnum):
    NONE = "none"
    DAILY = "daily"
    WEEKLY = "weekly"


class NotificationCategory(StrEnum):
    REMINDER = "reminder"
    PARTICIPATION_REQUEST = "participation_request"
    PARTICIPATION_RESPONSE = "participation_response"
    SHORTAGE = "shortage"
    REALLOCATION = "reallocation"
    ORDER_UPDATE = "order_update"
    COLLECTION = "collection"
    QUALITY = "quality"
    FULFILMENT = "fulfilment"
    BUYER_OPPORTUNITY = "buyer_opportunity"


class CropHealthClass(StrEnum):
    HEALTHY = "healthy"
    POSSIBLE_DISEASE = "possible_disease"
    STRESS = "stress"
    POSSIBLE_DEFICIENCY = "possible_deficiency"
    UNKNOWN = "unknown"
