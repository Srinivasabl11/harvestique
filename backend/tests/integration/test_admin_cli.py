"""The create-admin operator command (admins cannot be created via the public API)."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.cli.create_admin import PASSWORD_ENV, main
from tests.conftest import bearer, login_and_verify

pytestmark = pytest.mark.integration


def test_cli_creates_a_working_admin(db_client, db_container, monkeypatch, capsys):
    monkeypatch.setenv(PASSWORD_ENV, "AdminPass123")
    assert main(["--phone", "9000000042", "--name", "Ops Admin", "--email", "ops@example.com"], db_container) == 0
    assert "Created admin" in capsys.readouterr().out

    signed_in = login_and_verify(db_client, "+919000000042", "AdminPass123")  # admins also need the SMS code
    assert signed_in["user"]["role"] == "admin"
    assert signed_in["user"]["farmer_profile"] is None and signed_in["user"]["buyer_profile"] is None
    token = signed_in["tokens"]["access_token"]
    assert db_client.get("/api/v1/admin/users", headers=bearer(token)).status_code == 200


def test_cli_rejects_weak_password_and_creates_nothing(db_container, monkeypatch, capsys):
    monkeypatch.setenv(PASSWORD_ENV, "weak")
    assert main(["--phone", "9000000042", "--name", "Ops Admin"], db_container) == 2
    assert "password" in capsys.readouterr().err
    with db_container.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM users")) == 0


def test_cli_reports_duplicate_phone(db_container, monkeypatch, capsys):
    monkeypatch.setenv(PASSWORD_ENV, "AdminPass123")
    assert main(["--phone", "9000000042", "--name", "Ops Admin"], db_container) == 0
    assert main(["--phone", "+91 90000 00042", "--name", "Other"], db_container) == 1
    assert "already registered" in capsys.readouterr().err
