"""Application factory. Run with: uvicorn app.main:create_app --factory"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.container import Container, build_container
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    container = container or build_container(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if settings.seed_crop_catalog_on_startup and settings.app_env != "test":
            _seed_empty_catalog(app.state.container)
        yield
        app.state.container.shutdown()

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        debug=settings.debug,
        lifespan=lifespan,
        openapi_url=f"{settings.api_v1_prefix}/openapi.json",
        docs_url=f"{settings.api_v1_prefix}/docs",
    )
    app.state.container = container

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    return app


def _seed_empty_catalog(container: Container) -> None:
    """Best effort: a missing database must not stop the API from starting (health checks report it)."""
    from app.cli.seed_crops import seed_if_empty

    try:
        created = seed_if_empty(container)
        if created:
            logger.info("crop catalog was empty: %s standard crops created", created)
    except Exception:
        logger.warning("could not check or seed the crop catalog at startup", exc_info=True)
