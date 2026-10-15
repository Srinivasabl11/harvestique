"""Weather, harvest predictions, farm risk, prediction feedback and calibration."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import AdminDep, CurrentUserDep, FarmerDep, PageDep, PredictionServiceDep, WeatherServiceDep
from app.api.responses import AUTH_ONLY, ERR, WRITE_ERR
from app.schemas.common import Page
from app.schemas.intelligence import (
    CalibrationOut,
    FarmRiskOut,
    FarmWeatherOut,
    FeedbackReport,
    HarvestActualIn,
    HarvestCorrectionIn,
    PredictionOut,
    PredictionRequest,
    WeatherNowOut,
)

router = APIRouter()


@router.get(
    "/farms/{farm_id}/weather/now",
    response_model=WeatherNowOut,
    summary="Current conditions, rain chance (next hours, 7 days) for the farm card (model estimates, cached 15 min)",
    responses=ERR,
)
def farm_weather_now(farm_id: uuid.UUID, farmer: FarmerDep, weather: WeatherServiceDep) -> WeatherNowOut:
    return weather.farm_now(farmer.user_id, farm_id)


@router.get(
    "/farms/{farm_id}/weather",
    response_model=FarmWeatherOut,
    summary="Forecast and recent weather for a farm",
    responses=WRITE_ERR,
)
def farm_weather(
    farm_id: uuid.UUID, farmer: FarmerDep, weather: WeatherServiceDep, days: Annotated[int, Query(ge=1, le=16)] = 7
) -> FarmWeatherOut:
    return weather.farm_weather(farmer.user_id, farm_id, days)


@router.post(
    "/crop-cycles/{cycle_id}/predictions",
    response_model=PredictionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new prediction version (p10/p50/p90, harvest window, confidence, risk)",
    responses=WRITE_ERR,
)
def create_prediction(
    cycle_id: uuid.UUID, farmer: FarmerDep, predictions: PredictionServiceDep, payload: PredictionRequest | None = None
) -> PredictionOut:
    return predictions.create(farmer.user_id, cycle_id, payload or PredictionRequest())


@router.get(
    "/crop-cycles/{cycle_id}/predictions",
    response_model=Page[PredictionOut],
    summary="All prediction versions, newest first",
    responses=ERR,
)
def list_predictions(
    cycle_id: uuid.UUID, farmer: FarmerDep, predictions: PredictionServiceDep, page: PageDep
) -> Page[PredictionOut]:
    return predictions.list_for_cycle(farmer.user_id, cycle_id, limit=page.limit, offset=page.offset)


@router.get("/predictions/{prediction_id}", response_model=PredictionOut, responses=ERR)
def get_prediction(prediction_id: uuid.UUID, farmer: FarmerDep, predictions: PredictionServiceDep) -> PredictionOut:
    return predictions.get(farmer.user_id, prediction_id)


@router.patch(
    "/crop-cycles/{cycle_id}/harvest-actual",
    response_model=FeedbackReport,
    summary="Correct a recorded harvest (only before produce from it reached a collection hub)",
    responses=WRITE_ERR,
)
def correct_actual(
    cycle_id: uuid.UUID, payload: HarvestCorrectionIn, farmer: FarmerDep, predictions: PredictionServiceDep
) -> FeedbackReport:
    return predictions.correct_actual(farmer.user_id, cycle_id, payload)


@router.post(
    "/crop-cycles/{cycle_id}/harvest-actual",
    response_model=FeedbackReport,
    status_code=status.HTTP_201_CREATED,
    summary="Record the MEASURED harvest; scores every prediction version and updates calibration",
    responses=WRITE_ERR,
)
def record_actual(
    cycle_id: uuid.UUID, payload: HarvestActualIn, farmer: FarmerDep, predictions: PredictionServiceDep
) -> FeedbackReport:
    return predictions.record_actual(farmer.user_id, cycle_id, payload)


@router.get(
    "/crop-cycles/{cycle_id}/feedback",
    response_model=FeedbackReport,
    summary="Predicted vs actual for each version",
    responses=ERR,
)
def get_feedback(cycle_id: uuid.UUID, farmer: FarmerDep, predictions: PredictionServiceDep) -> FeedbackReport:
    return predictions.feedback_report(farmer.user_id, cycle_id)


@router.get(
    "/farms/{farm_id}/risk", response_model=FarmRiskOut, summary="Farm risk across open crop cycles", responses=ERR
)
def farm_risk(farm_id: uuid.UUID, farmer: FarmerDep, predictions: PredictionServiceDep) -> FarmRiskOut:
    return predictions.farm_risk(farmer.user_id, farm_id)


@router.get(
    "/calibration",
    response_model=list[CalibrationOut],
    summary="Latest calibration profiles (aggregate statistics only)",
    responses=AUTH_ONLY,
)
def get_calibration(_user: CurrentUserDep, predictions: PredictionServiceDep) -> list[CalibrationOut]:
    return predictions.latest_calibration()


@router.post(
    "/admin/calibration/recompute",
    response_model=list[CalibrationOut],
    summary="Recompute calibration profiles (admin)",
    responses=ERR,
)
def recompute_calibration(_admin: AdminDep, predictions: PredictionServiceDep) -> list[CalibrationOut]:
    return predictions.recompute_all()
