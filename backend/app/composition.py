"""Service factories: the single place that assembles services from a session + container.

Used by FastAPI dependencies (api/deps.py), the admin CLI and tests, so wiring is never duplicated.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.container import Container
from app.repositories.auth import LoginAttemptRepository, RefreshTokenRepository
from app.repositories.crops import CropCycleRepository, CropRepository
from app.repositories.engagement import EngagementRepository
from app.repositories.farm_records import ActivityRepository, ExpenseRepository, ObservationRepository
from app.repositories.farms import FarmRepository, PlotRepository
from app.repositories.intelligence import (
    ActualRepository,
    CalibrationRepository,
    FeedbackRepository,
    InventoryRepository,
    PredictionRepository,
    WeatherRepository,
)
from app.repositories.marketplace import MarketplaceRepository
from app.repositories.planning import CropPlanItemRepository, CropPlanRepository
from app.repositories.pooling import PoolingRepository
from app.repositories.users import UserRepository
from app.services.assistant import AssistantService
from app.services.auth import AuthService
from app.services.crop_cycles import CropCycleService
from app.services.crop_plans import CropPlanService
from app.services.crops import CropService
from app.services.engagement import NotificationService, ReminderService
from app.services.farm_records import ActivityService, ExpenseService, ObservationService
from app.services.farms import FarmService, PlotService
from app.services.grading import GradingService
from app.services.insights import InsightService
from app.services.inventory import InventoryService
from app.services.market_prices import MarketPriceService
from app.services.marketplace import MarketplaceService
from app.services.media import CropHealthService, SpeechService
from app.services.planning import PlanningService
from app.services.pooling import PoolService
from app.services.predictions import PredictionService
from app.services.users import UserService
from app.services.weather import WeatherService


def build_auth_service(session: Session, container: Container) -> AuthService:
    return AuthService(
        session=session,
        users=UserRepository(session),
        refresh_tokens=RefreshTokenRepository(session),
        login_attempts=LoginAttemptRepository(session),
        hasher=container.passwords,
        codec=container.tokens,
        clock=container.clock,  # read per call so tests can swap the clock
        settings=container.settings,
    )


def build_user_service(session: Session) -> UserService:
    return UserService(UserRepository(session))


# ------------------------------------------------------------------ farming


def build_crop_service(session: Session) -> CropService:
    return CropService(session=session, crops=CropRepository(session))


def build_farm_service(session: Session) -> FarmService:
    return FarmService(session=session, farms=FarmRepository(session), plots=PlotRepository(session))


def build_plot_service(session: Session) -> PlotService:
    return PlotService(
        session=session,
        farms=FarmRepository(session),
        plots=PlotRepository(session),
        cycles=CropCycleRepository(session),
    )


def build_crop_cycle_service(session: Session, container: Container) -> CropCycleService:
    return CropCycleService(
        session=session,
        farms=FarmRepository(session),
        plots=PlotRepository(session),
        crops=CropRepository(session),
        cycles=CropCycleRepository(session),
        clock=container.clock,
    )


def build_expense_service(session: Session, container: Container) -> ExpenseService:
    return ExpenseService(
        session=session,
        farms=FarmRepository(session),
        cycles=CropCycleRepository(session),
        expenses=ExpenseRepository(session),
        clock=container.clock,
    )


def build_activity_service(session: Session, container: Container) -> ActivityService:
    return ActivityService(
        session=session,
        farms=FarmRepository(session),
        plots=PlotRepository(session),
        cycles=CropCycleRepository(session),
        activities=ActivityRepository(session),
        clock=container.clock,
    )


def build_observation_service(session: Session, container: Container) -> ObservationService:
    return ObservationService(
        session=session,
        cycles=CropCycleRepository(session),
        observations=ObservationRepository(session),
        clock=container.clock,
    )


# ----------------------------------------------------------------- planning


def build_planning_service() -> PlanningService:
    return PlanningService()  # stateless: needs neither a session nor a clock


def build_crop_plan_service(session: Session) -> CropPlanService:
    return CropPlanService(
        session=session,
        plans=CropPlanRepository(session),
        items=CropPlanItemRepository(session),
        farms=FarmRepository(session),
        crops=CropRepository(session),
    )


# ------------------------------------------------------------- intelligence


def build_weather_service(session: Session, container: Container) -> WeatherService:
    return WeatherService(
        session=session,
        repo=WeatherRepository(session),
        provider=container.weather,
        clock=container.clock,
        settings=container.settings,
    )


def build_inventory_service(session: Session) -> InventoryService:
    return InventoryService(
        session=session,
        repo=InventoryRepository(session),
        predictions=PredictionRepository(session),
        actuals=ActualRepository(session),
    )


def build_prediction_service(session: Session, container: Container) -> PredictionService:
    return PredictionService(
        session=session,
        predictions=PredictionRepository(session),
        actuals=ActualRepository(session),
        feedback=FeedbackRepository(session),
        calibration=CalibrationRepository(session),
        inventory=build_inventory_service(session),
        inventory_repo=InventoryRepository(session),
        weather=build_weather_service(session, container),
        predictor=container.predictor,
        clock=container.clock,
        settings=container.settings,
        on_lot_changed=build_pool_service(session, container).on_lot_changed,
    )


def build_pool_service(session: Session, container: Container) -> PoolService:
    """The pool service always comes wired to the marketplace (order sync, buyer-opportunity notifications)."""
    return build_marketplace_service(session, container)[1]


def build_notification_service(session: Session, container: Container) -> NotificationService:
    return NotificationService(
        session=session, repo=EngagementRepository(session), clock=container.clock, channel=container.notifications
    )


def build_reminder_service(session: Session, container: Container) -> ReminderService:
    return ReminderService(
        session=session,
        repo=EngagementRepository(session),
        clock=container.clock,
        notifications=build_notification_service(session, container),
    )


def build_marketplace_service(session: Session, container: Container) -> tuple[MarketplaceService, PoolService]:
    pools = PoolService(
        session=session,
        repo=PoolingRepository(session),
        inventory=build_inventory_service(session),
        clock=container.clock,
    )
    market = MarketplaceService(
        session=session,
        repo=MarketplaceRepository(session),
        pool_repo=PoolingRepository(session),
        pools=pools,
        notifications=build_notification_service(session, container),
        clock=container.clock,
    )
    pools.set_hooks(after_change=market.sync_pool, on_demand_created=market.notify_demand)
    return market, pools


def build_insight_service(session: Session, container: Container) -> InsightService:
    return InsightService(session=session, clock=container.clock)


def build_assistant_service(session: Session, container: Container) -> AssistantService:
    return AssistantService(
        clock=container.clock,
        llm=container.llm,
        farms=build_farm_service(session),
        weather=build_weather_service(session, container),
        predictions=build_prediction_service(session, container),
        inventory=build_inventory_service(session),
        reminders=build_reminder_service(session, container),
        marketplace=build_marketplace_service(session, container)[0],
        plans=build_crop_plan_service(session),
        engagement_repo=EngagementRepository(session),
        expenses=build_expense_service(session, container),
        llm_intents=container.settings.assistant_llm_intents,
        llm_general_answers=container.settings.assistant_llm_general_answers,
        llm_general_answers_kannada=container.settings.assistant_llm_general_answers_kannada,
        llm_rewording=container.settings.assistant_llm_rewording,
        market_prices=MarketPriceService(session, container.market_prices, container.clock),
    )


def build_crop_health_service(session: Session, container: Container) -> CropHealthService:
    return CropHealthService(
        session=session,
        repo=EngagementRepository(session),
        classifier=container.crop_health,
        photo_limit=container.ai_photo_limit,
    )


def build_grading_service(session: Session, container: Container) -> GradingService:
    return GradingService(
        session=session,
        grader=container.produce_grader,
        update_lot=build_pool_service(session, container).update_lot,
        clock=container.clock,
        photo_limit=container.ai_photo_limit,
    )


def build_speech_service(container: Container) -> SpeechService:
    return SpeechService(stt=container.speech, tts=container.speech)
