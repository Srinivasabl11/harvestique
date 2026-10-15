"""The migrated database matches the models, and DB-level integrity rules hold."""

from __future__ import annotations

import uuid

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app.models.base import Base

pytestmark = pytest.mark.integration


def test_expected_tables_exist(migrated_db):
    tables = set(inspect(create_engine(migrated_db)).get_table_names())
    assert {"users", "farmer_profiles", "buyer_profiles", "refresh_tokens", "login_attempts"} <= tables


def test_models_and_migrations_have_no_drift(migrated_db):
    """Equivalent of `alembic check`: a model change without a migration fails the build."""
    engine = create_engine(migrated_db)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
    assert diff == []


def _insert_user(conn, *, phone="+919000000009", role="farmer", email=None):
    conn.execute(
        text(
            "INSERT INTO users (id, phone, email, password_hash, full_name, role, is_active) "
            "VALUES (:id, :phone, :email, 'x', 'Test', :role, true)"
        ),
        {"id": uuid.uuid4(), "phone": phone, "email": email, "role": role},
    )


def test_db_rejects_unknown_role(db_container):
    with pytest.raises(IntegrityError), db_container.engine.begin() as conn:
        _insert_user(conn, role="superuser")


def test_db_enforces_unique_phone_and_email(db_container):
    with db_container.engine.begin() as conn:
        _insert_user(conn, phone="+919000000010", email="a@example.com")
    with pytest.raises(IntegrityError), db_container.engine.begin() as conn:
        _insert_user(conn, phone="+919000000010")
    with pytest.raises(IntegrityError), db_container.engine.begin() as conn:
        _insert_user(conn, phone="+919000000011", email="a@example.com")


def test_deleting_user_cascades_to_profile_and_tokens(db_client, db_container, register_farmer):
    data = register_farmer()
    with db_container.engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": data["user"]["id"]})
        assert conn.scalar(text("SELECT count(*) FROM farmer_profiles")) == 0
        assert conn.scalar(text("SELECT count(*) FROM refresh_tokens")) == 0
