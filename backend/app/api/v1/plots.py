"""Plot endpoints (farmer-only). Creation/listing is nested under a farm; the rest by plot id."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from app.api.deps import FarmerDep, PageDep, PlotServiceDep
from app.api.responses import ERR, WRITE_ERR
from app.schemas.common import Page
from app.schemas.farms import PlotCreate, PlotRead, PlotUpdate

router = APIRouter()


@router.post(
    "/farms/{farm_id}/plots", response_model=PlotRead, status_code=status.HTTP_201_CREATED, responses=WRITE_ERR
)
def create_plot(farm_id: uuid.UUID, payload: PlotCreate, farmer: FarmerDep, plots: PlotServiceDep) -> PlotRead:
    return plots.create(farmer.user_id, farm_id, payload)


@router.get("/farms/{farm_id}/plots", response_model=Page[PlotRead], responses=ERR)
def list_plots(
    farm_id: uuid.UUID, farmer: FarmerDep, plots: PlotServiceDep, page: PageDep, include_archived: bool = False
) -> Page[PlotRead]:
    return plots.list_for_farm(
        farmer.user_id, farm_id, include_archived=include_archived, limit=page.limit, offset=page.offset
    )


@router.get("/plots/{plot_id}", response_model=PlotRead, responses=ERR)
def get_plot(plot_id: uuid.UUID, farmer: FarmerDep, plots: PlotServiceDep) -> PlotRead:
    return plots.get(farmer.user_id, plot_id)


@router.patch("/plots/{plot_id}", response_model=PlotRead, responses=WRITE_ERR)
def update_plot(plot_id: uuid.UUID, payload: PlotUpdate, farmer: FarmerDep, plots: PlotServiceDep) -> PlotRead:
    return plots.update(farmer.user_id, plot_id, payload)


@router.delete(
    "/plots/{plot_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=WRITE_ERR,
)
def delete_plot(plot_id: uuid.UUID, farmer: FarmerDep, plots: PlotServiceDep) -> Response:
    plots.delete(farmer.user_id, plot_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
