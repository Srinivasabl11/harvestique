"""Runs only when TEST_DATABASE_URL points at a disposable PostgreSQL database."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, inspect

from app.core.database import ping_database

DB_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set"),
]


def test_ping_real_database():
    assert ping_database(create_engine(DB_URL))


def test_migrations_upgrade_and_downgrade():
    from alembic import command

    from tests.conftest import alembic_config

    cfg = alembic_config(DB_URL)
    command.upgrade(cfg, "head")
    assert "alembic_version" in inspect(create_engine(DB_URL)).get_table_names()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
