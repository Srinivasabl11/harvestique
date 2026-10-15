"""Farm expense endpoints (farmer-only)."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Response, status

from app.api.deps import ExpenseServiceDep, FarmerDep, PageDep
from app.api.responses import ERR, WRITE_ERR
from app.core.enums import ExpenseCategory
from app.schemas.common import Page
from app.schemas.farm_records import ExpenseCreate, ExpenseRead, ExpenseUpdate

router = APIRouter()


@router.post(
    "/farms/{farm_id}/expenses", response_model=ExpenseRead, status_code=status.HTTP_201_CREATED, responses=WRITE_ERR
)
def create_expense(
    farm_id: uuid.UUID, payload: ExpenseCreate, farmer: FarmerDep, expenses: ExpenseServiceDep
) -> ExpenseRead:
    return expenses.create(farmer.user_id, farm_id, payload)


@router.get("/farms/{farm_id}/expenses", response_model=Page[ExpenseRead], responses=ERR)
def list_expenses(
    farm_id: uuid.UUID,
    farmer: FarmerDep,
    expenses: ExpenseServiceDep,
    page: PageDep,
    crop_cycle_id: uuid.UUID | None = None,
    category: ExpenseCategory | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> Page[ExpenseRead]:
    return expenses.list_for_farm(
        farmer.user_id,
        farm_id,
        crop_cycle_id=crop_cycle_id,
        category=category,
        date_from=date_from,
        date_to=date_to,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/expenses/{expense_id}", response_model=ExpenseRead, responses=ERR)
def get_expense(expense_id: uuid.UUID, farmer: FarmerDep, expenses: ExpenseServiceDep) -> ExpenseRead:
    return expenses.get(farmer.user_id, expense_id)


@router.patch("/expenses/{expense_id}", response_model=ExpenseRead, responses=WRITE_ERR)
def update_expense(
    expense_id: uuid.UUID, payload: ExpenseUpdate, farmer: FarmerDep, expenses: ExpenseServiceDep
) -> ExpenseRead:
    return expenses.update(farmer.user_id, expense_id, payload)


@router.delete("/expenses/{expense_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response, responses=ERR)
def delete_expense(expense_id: uuid.UUID, farmer: FarmerDep, expenses: ExpenseServiceDep) -> Response:
    expenses.delete(farmer.user_id, expense_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
