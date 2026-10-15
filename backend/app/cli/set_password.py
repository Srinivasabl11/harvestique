"""Set the password of any account, admins included (the in-app reset is for farmers and buyers only).

    python -m app.cli.set_password --phone +919876543210

The password is prompted for (hidden). For automation set HARVESTIQUE_NEW_PASSWORD. Every session of the account is
signed out and any sign-in lockout is cleared. Check who is asking before using it: sign-in has no second factor.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from collections.abc import Sequence

from pydantic import TypeAdapter, ValidationError

from app.composition import build_auth_service
from app.core.config import get_settings
from app.core.container import Container, build_container
from app.core.errors import AppError
from app.schemas.auth import NewPassword, PhoneNumber

PASSWORD_ENV = "HARVESTIQUE_NEW_PASSWORD"  # noqa: S105 - env var *name*, not a secret


def _read_password() -> str:
    from_env = os.environ.get(PASSWORD_ENV)
    if from_env:
        return from_env
    first = getpass.getpass("New password: ")
    if first != getpass.getpass("Repeat new password: "):
        raise SystemExit("Passwords do not match")
    return first


def main(argv: Sequence[str] | None = None, container: Container | None = None) -> int:
    parser = argparse.ArgumentParser(description="Set a Harvestique account's password")
    parser.add_argument("--phone", required=True)
    args = parser.parse_args(argv)

    try:
        phone = TypeAdapter(PhoneNumber).validate_python(args.phone)
        password = TypeAdapter(NewPassword).validate_python(_read_password())
    except ValidationError as exc:
        for err in exc.errors():
            print(f"error: {str(err['msg']).removeprefix('Value error, ')}", file=sys.stderr)
        return 2

    owns_container = container is None
    container = container or build_container(get_settings())
    try:
        with container.session_factory() as session:
            user = build_auth_service(session, container).operator_set_password(phone, password)
        print(f"Password set for {user.role.value} {user.id} ({user.phone}); all of its sessions were signed out")
        return 0
    except AppError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return 1
    finally:
        if owns_container:
            container.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
