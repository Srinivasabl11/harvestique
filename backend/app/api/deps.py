"""FastAPI dependency providers - the bridge between HTTP and the DI container.

Routes declare what they need (a service, a session); they never construct
providers or repositories themselves.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.composition import (
    build_activity_service,
    build_assistant_service,
    build_auth_service,
    build_crop_cycle_service,
    build_crop_health_service,
    build_crop_plan_service,
    build_crop_service,
    build_expense_service,
    build_farm_service,
    build_insight_service,
    build_inventory_service,
    build_marketplace_service,
    build_notification_service,
    build_observation_service,
    build_planning_service,
    build_plot_service,
    build_pool_service,
    build_prediction_service,
    build_reminder_service,
    build_speech_service,
    build_user_service,
    build_weather_service,
)
from app.core.config import Settings
from app.core.container import Container
from app.core.enums import UserRole
from app.core.errors import AuthenticationError, PermissionDeniedError
from app.schemas.auth import CurrentUser
from app.schemas.common import PageParams
from app.services.assistant import AssistantService
from app.services.auth import AuthService
from app.services.crop_cycles import CropCycleService
from app.services.crop_plans import CropPlanService
from app.services.crops import CropService
from app.services.engagement import NotificationService, ReminderService
from app.services.farm_records import ActivityService, ExpenseService, ObservationService
from app.services.farms import FarmService, PlotService
from app.services.insights import InsightService
from app.services.inventory import InventoryService
from app.services.marketplace import MarketplaceService
from app.services.media import CropHealthService, SpeechService
from app.services.planning import PlanningService
from app.services.pooling import PoolService
from app.services.predictions import PredictionService
from app.services.system_health import SystemHealthService
from app.services.users import UserService
from app.services.weather import WeatherService


def get_container(request: Request) -> Container:
    return request.app.state.container  # type: ignore[no-any-return]


ContainerDep = Annotated[Container, Depends(get_container)]


def get_settings_dep(container: ContainerDep) -> Settings:
    return container.settings


def get_db_session(container: ContainerDep) -> Iterator[Session]:
    """One session per request. Services commit explicitly; errors roll back."""
    session = container.session_factory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


SessionDep = Annotated[Session, Depends(get_db_session)]


def get_system_health_service(container: ContainerDep) -> SystemHealthService:
    return SystemHealthService(db_check=container.check_database, llm=container.llm)


# ----------------------------------------------------------------- services


def get_auth_service(session: SessionDep, container: ContainerDep) -> AuthService:
    return build_auth_service(session, container)


def get_user_service(session: SessionDep) -> UserService:
    return build_user_service(session)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
UserServiceDep = Annotated[UserService, Depends(get_user_service)]


# ----------------------------------------------------- authentication / RBAC

# auto_error=False: we raise our own AuthenticationError so 401s use the standard error envelope.
bearer_scheme = HTTPBearer(
    auto_error=False, description="Access token from /auth/login/verify or /auth/register/verify"
)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    auth: AuthServiceDep,
) -> CurrentUser:
    if credentials is None:
        raise AuthenticationError("Authentication required", code="not_authenticated")
    return auth.authenticate(credentials.credentials)


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]


def require_roles(*roles: UserRole) -> Callable[[CurrentUser], CurrentUser]:
    """Build a dependency allowing only the given roles (403 otherwise)."""

    def checker(user: CurrentUserDep) -> CurrentUser:
        if user.role not in roles:
            raise PermissionDeniedError("You do not have permission to perform this action")
        return user

    return checker


FarmerDep = Annotated[CurrentUser, Depends(require_roles(UserRole.FARMER))]
BuyerDep = Annotated[CurrentUser, Depends(require_roles(UserRole.BUYER))]
AdminDep = Annotated[CurrentUser, Depends(require_roles(UserRole.ADMIN))]


# ------------------------------------------------------------------ farming


def page_params(
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PageParams:
    return PageParams(limit=limit, offset=offset)


PageDep = Annotated[PageParams, Depends(page_params)]


def get_crop_service(session: SessionDep) -> CropService:
    return build_crop_service(session)


def get_farm_service(session: SessionDep) -> FarmService:
    return build_farm_service(session)


def get_plot_service(session: SessionDep) -> PlotService:
    return build_plot_service(session)


def get_crop_cycle_service(session: SessionDep, container: ContainerDep) -> CropCycleService:
    return build_crop_cycle_service(session, container)


def get_expense_service(session: SessionDep, container: ContainerDep) -> ExpenseService:
    return build_expense_service(session, container)


def get_activity_service(session: SessionDep, container: ContainerDep) -> ActivityService:
    return build_activity_service(session, container)


def get_observation_service(session: SessionDep, container: ContainerDep) -> ObservationService:
    return build_observation_service(session, container)


CropServiceDep = Annotated[CropService, Depends(get_crop_service)]
FarmServiceDep = Annotated[FarmService, Depends(get_farm_service)]
PlotServiceDep = Annotated[PlotService, Depends(get_plot_service)]
CropCycleServiceDep = Annotated[CropCycleService, Depends(get_crop_cycle_service)]
ExpenseServiceDep = Annotated[ExpenseService, Depends(get_expense_service)]
ActivityServiceDep = Annotated[ActivityService, Depends(get_activity_service)]
ObservationServiceDep = Annotated[ObservationService, Depends(get_observation_service)]


# ----------------------------------------------------------------- planning


def get_planning_service() -> PlanningService:
    return build_planning_service()


def get_crop_plan_service(session: SessionDep) -> CropPlanService:
    return build_crop_plan_service(session)


PlanningServiceDep = Annotated[PlanningService, Depends(get_planning_service)]
CropPlanServiceDep = Annotated[CropPlanService, Depends(get_crop_plan_service)]


# ------------------------------------------------------------- intelligence


def get_weather_service(session: SessionDep, container: ContainerDep) -> WeatherService:
    return build_weather_service(session, container)


def get_prediction_service(session: SessionDep, container: ContainerDep) -> PredictionService:
    return build_prediction_service(session, container)


def get_inventory_service(session: SessionDep) -> InventoryService:
    return build_inventory_service(session)


WeatherServiceDep = Annotated[WeatherService, Depends(get_weather_service)]
PredictionServiceDep = Annotated[PredictionService, Depends(get_prediction_service)]
InventoryServiceDep = Annotated[InventoryService, Depends(get_inventory_service)]


# ----------------------------------------------------------------- pooling


def get_pool_service(session: SessionDep, container: ContainerDep) -> PoolService:
    return build_pool_service(session, container)


PoolServiceDep = Annotated[PoolService, Depends(get_pool_service)]
BuyerOrAdminDep = Annotated[CurrentUser, Depends(require_roles(UserRole.BUYER, UserRole.ADMIN))]


# ------------------------------------------------- marketplace / engagement / AI


def get_marketplace_service(session: SessionDep, container: ContainerDep) -> MarketplaceService:
    return build_marketplace_service(session, container)[0]


def get_notification_service(session: SessionDep, container: ContainerDep) -> NotificationService:
    return build_notification_service(session, container)


def get_reminder_service(session: SessionDep, container: ContainerDep) -> ReminderService:
    return build_reminder_service(session, container)


def get_insight_service(session: SessionDep, container: ContainerDep) -> InsightService:
    return build_insight_service(session, container)


def get_assistant_service(session: SessionDep, container: ContainerDep) -> AssistantService:
    return build_assistant_service(session, container)


def get_crop_health_service(session: SessionDep, container: ContainerDep) -> CropHealthService:
    return build_crop_health_service(session, container)


def get_speech_service(container: ContainerDep) -> SpeechService:
    return build_speech_service(container)


MarketplaceServiceDep = Annotated[MarketplaceService, Depends(get_marketplace_service)]
NotificationServiceDep = Annotated[NotificationService, Depends(get_notification_service)]
ReminderServiceDep = Annotated[ReminderService, Depends(get_reminder_service)]
InsightServiceDep = Annotated[InsightService, Depends(get_insight_service)]
AssistantServiceDep = Annotated[AssistantService, Depends(get_assistant_service)]
CropHealthServiceDep = Annotated[CropHealthService, Depends(get_crop_health_service)]
SpeechServiceDep = Annotated[SpeechService, Depends(get_speech_service)]
FarmerOrBuyerDep = Annotated[CurrentUser, Depends(require_roles(UserRole.FARMER, UserRole.BUYER))]
