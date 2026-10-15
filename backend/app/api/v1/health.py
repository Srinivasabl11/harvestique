"""Liveness and readiness probes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app import __version__
from app.api.deps import ContainerDep, get_system_health_service
from app.schemas.common import LivenessResponse, ReadinessResponse
from app.services.system_health import SystemHealthService

router = APIRouter()


@router.get("/live", response_model=LivenessResponse)
def live(container: ContainerDep) -> LivenessResponse:
    return LivenessResponse(service=container.settings.app_name, version=__version__)


@router.get("/ready", response_model=ReadinessResponse)
def ready(
    response: Response,
    service: Annotated[SystemHealthService, Depends(get_system_health_service)],
) -> ReadinessResponse:
    result = service.readiness()
    if result.status == "not_ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result
