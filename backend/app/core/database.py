"""SQLAlchemy engine / session factory construction.

Engines are created by the composition root (`container.build_container`), never
at import time, so importing the app has no side effects.
"""

from __future__ import annotations

import logging

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings

logger = logging.getLogger(__name__)


def build_engine(settings: Settings) -> Engine:
    return create_engine(
        settings.database_url,
        echo=settings.db_echo,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def ping_database(engine: Engine) -> bool:
    """Return True if the database answers `SELECT 1`."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError as exc:
        logger.warning("Database ping failed: %s", exc.__class__.__name__)
        return False
