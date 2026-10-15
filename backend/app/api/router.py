"""Top-level API router. Each bounded context contributes one or more v1 routers."""

from fastapi import APIRouter

from app.api.v1 import (
    activities,
    admin,
    assistant,
    auth,
    buyers,
    crop_cycles,
    crop_plans,
    crops,
    engagement,
    expenses,
    farmers,
    farms,
    health,
    intelligence,
    inventory,
    marketplace,
    observations,
    planning,
    plots,
    pooling,
)

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(farmers.router, prefix="/farmers", tags=["farmers"])
api_router.include_router(buyers.router, prefix="/buyers", tags=["buyers"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(crops.router, prefix="/crops", tags=["crop catalog"])
api_router.include_router(farms.router, prefix="/farms", tags=["farms"])
api_router.include_router(plots.router, tags=["plots"])
api_router.include_router(crop_cycles.router, tags=["crop cycles"])
api_router.include_router(expenses.router, tags=["expenses"])
api_router.include_router(activities.router, tags=["activities"])
api_router.include_router(observations.router, tags=["observations"])
api_router.include_router(planning.router, prefix="/planning", tags=["planning"])
api_router.include_router(crop_plans.router, tags=["crop plans"])
api_router.include_router(intelligence.router, tags=["intelligence"])
api_router.include_router(inventory.router, tags=["inventory"])
api_router.include_router(pooling.router, tags=["harvest pooling"])
api_router.include_router(marketplace.router, tags=["marketplace"])
api_router.include_router(engagement.router, tags=["reminders, notifications and calendar"])
api_router.include_router(assistant.router, tags=["assistant, voice and crop health"])
