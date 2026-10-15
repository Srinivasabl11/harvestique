"""Create an admin account. Admins cannot be created through the public API.

    python -m app.cli.create_admin --phone +919876543210 --name "Admin" [--email a@b.com]

The password is prompted for (hidden). For automation set HARVESTIQUE_ADMIN_PASSWORD.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from collections.abc import Sequence

from pydantic import ValidationError

from app.composition import build_auth_service
from app.core.config import get_settings
from app.core.container import Container, build_container
from app.core.errors import AppError
from app.schemas.auth import AdminCreateRequest

PASSWORD_ENV = "HARVESTIQUE_ADMIN_PASSWORD"  # noqa: S105 - env var *name*, not a secret


def _read_password() -> str:
    from_env = os.environ.get(PASSWORD_ENV)
    if from_env:
        return from_env
    first = getpass.getpass("Password: ")
    if first != getpass.getpass("Repeat password: "):
        raise SystemExit("Passwords do not match")
    return first


def main(argv: Sequence[str] | None = None, container: Container | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a Harvestique admin user")
    parser.add_argument("--phone", required=True)
    parser.add_argument("--name", required=True, dest="full_name")
    parser.add_argument("--email")
    args = parser.parse_args(argv)

    try:
        request = AdminCreateRequest(
            phone=args.phone, password=_read_password(), full_name=args.full_name, email=args.email
        )
    except ValidationError as exc:
        for err in exc.errors():
            field = ".".join(str(p) for p in err["loc"])
            print(f"error: {field}: {str(err['msg']).removeprefix('Value error, ')}", file=sys.stderr)
        return 2

    owns_container = container is None
    container = container or build_container(get_settings())
    try:
        with container.session_factory() as session:
            user = build_auth_service(session, container).create_admin(request)
        print(f"Created admin {user.id} ({user.phone})")
        return 0
    except AppError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return 1
    finally:
        if owns_container:
            container.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
