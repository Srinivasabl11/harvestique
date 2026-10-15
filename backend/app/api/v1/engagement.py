"""Reminders, notifications, farm calendar, profile updates and the admin dashboard."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import (
    AdminDep,
    BuyerDep,
    CurrentUserDep,
    FarmerDep,
    FarmerOrBuyerDep,
    InsightServiceDep,
    NotificationServiceDep,
    PageDep,
    ReminderServiceDep,
    UserServiceDep,
)
from app.api.responses import AUTH_ONLY, ERR, WRITE_ERR
from app.core.enums import ReminderStatus
from app.schemas.auth import BuyerProfileRead, BuyerProfileUpdate, FarmerProfileRead, FarmerProfileUpdate
from app.schemas.common import Page
from app.schemas.engagement import (
    CalendarOut,
    DashboardOut,
    NotificationOut,
    ReminderCreate,
    ReminderOut,
    ReminderSuggestion,
    ReminderUpdate,
    UnreadCount,
)

router = APIRouter()


# ------------------------------------------------------------------ profiles
@router.patch(
    "/farmers/me",
    response_model=FarmerProfileRead,
    summary="Update my farmer profile (incl. preferred language)",
    responses=WRITE_ERR,
)
def update_farmer(payload: FarmerProfileUpdate, farmer: FarmerDep, users: UserServiceDep) -> FarmerProfileRead:
    return users.update_farmer_profile(farmer.user_id, payload)


@router.patch("/buyers/me", response_model=BuyerProfileRead, summary="Update my buyer profile", responses=WRITE_ERR)
def update_buyer(payload: BuyerProfileUpdate, buyer: BuyerDep, users: UserServiceDep) -> BuyerProfileRead:
    return users.update_buyer_profile(buyer.user_id, payload)


# ----------------------------------------------------------------- reminders
@router.post("/reminders", response_model=ReminderOut, status_code=status.HTTP_201_CREATED, responses=WRITE_ERR)
def create_reminder(
    payload: ReminderCreate, user: FarmerOrBuyerDep, reminders: ReminderServiceDep, from_suggestion: bool = False
) -> ReminderOut:
    return reminders.create(user.user_id, payload, source="suggestion" if from_suggestion else "user")


@router.get("/reminders", response_model=Page[ReminderOut], responses=ERR)
def list_reminders(
    user: FarmerOrBuyerDep,
    reminders: ReminderServiceDep,
    page: PageDep,
    status_filter: Annotated[ReminderStatus | None, Query(alias="status")] = None,
) -> Page[ReminderOut]:
    return reminders.list_reminders(user.user_id, status_filter, limit=page.limit, offset=page.offset)


@router.get(
    "/reminders/suggestions",
    response_model=list[ReminderSuggestion],
    summary="Reminders suggested from my recorded data",
    responses=ERR,
)
def suggestions(farmer: FarmerDep, reminders: ReminderServiceDep) -> list[ReminderSuggestion]:
    return reminders.suggestions(farmer.user_id)


@router.get("/reminders/{reminder_id}", response_model=ReminderOut, responses=ERR)
def get_reminder(reminder_id: uuid.UUID, user: FarmerOrBuyerDep, reminders: ReminderServiceDep) -> ReminderOut:
    return reminders.get(user.user_id, reminder_id)


@router.patch("/reminders/{reminder_id}", response_model=ReminderOut, responses=WRITE_ERR)
def update_reminder(
    reminder_id: uuid.UUID, payload: ReminderUpdate, user: FarmerOrBuyerDep, reminders: ReminderServiceDep
) -> ReminderOut:
    return reminders.update(user.user_id, reminder_id, payload)


@router.post(
    "/reminders/{reminder_id}/complete",
    response_model=ReminderOut,
    summary="Done (recurring reminders roll forward)",
    responses=WRITE_ERR,
)
def complete_reminder(reminder_id: uuid.UUID, user: FarmerOrBuyerDep, reminders: ReminderServiceDep) -> ReminderOut:
    return reminders.complete(user.user_id, reminder_id)


@router.delete(
    "/reminders/{reminder_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete one of my reminders",
    responses=ERR,
)
def delete_reminder(reminder_id: uuid.UUID, user: FarmerOrBuyerDep, reminders: ReminderServiceDep) -> Response:
    reminders.delete(user.user_id, reminder_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/reminders/{reminder_id}/dismiss", response_model=ReminderOut, responses=WRITE_ERR)
def dismiss_reminder(reminder_id: uuid.UUID, user: FarmerOrBuyerDep, reminders: ReminderServiceDep) -> ReminderOut:
    return reminders.dismiss(user.user_id, reminder_id)


# ------------------------------------------------------------- notifications
@router.get(
    "/notifications",
    response_model=Page[NotificationOut],
    summary="My notification feed (due reminders are added first)",
    responses=AUTH_ONLY,
)
def notifications(
    user: CurrentUserDep,
    feed: NotificationServiceDep,
    reminders: ReminderServiceDep,
    page: PageDep,
    unread_only: bool = False,
) -> Page[NotificationOut]:
    reminders.process_due(user.user_id)
    return feed.list_notifications(user.user_id, unread_only, limit=page.limit, offset=page.offset)


@router.get("/notifications/unread-count", response_model=UnreadCount, responses=AUTH_ONLY)
def unread(user: CurrentUserDep, feed: NotificationServiceDep, reminders: ReminderServiceDep) -> UnreadCount:
    reminders.process_due(user.user_id)
    return feed.unread(user.user_id)


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut, responses=ERR)
def mark_read(notification_id: uuid.UUID, user: CurrentUserDep, feed: NotificationServiceDep) -> NotificationOut:
    return feed.mark_read(user.user_id, notification_id)


@router.post("/notifications/read-all", response_model=UnreadCount, responses=AUTH_ONLY)
def mark_all_read(user: CurrentUserDep, feed: NotificationServiceDep) -> UnreadCount:
    return feed.mark_all_read(user.user_id)


# ------------------------------------------------------------------- calendar
@router.get(
    "/calendar", response_model=CalendarOut, summary="Farm / delivery calendar (max 180 days)", responses=WRITE_ERR
)
def calendar(user: FarmerOrBuyerDep, insights: InsightServiceDep, start: date, end: date) -> CalendarOut:
    return insights.calendar(user, start, end)


# ----------------------------------------------------------------- dashboard
@router.get(
    "/admin/dashboard",
    response_model=DashboardOut,
    summary="Platform counts and totals (real data only)",
    responses=ERR,
)
def dashboard(_admin: AdminDep, insights: InsightServiceDep) -> DashboardOut:
    return insights.dashboard()
