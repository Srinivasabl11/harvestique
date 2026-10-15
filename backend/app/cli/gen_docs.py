"""Generate docs/API.md and docs/DATABASE.md from the running application (routes, enforced roles, schemas) and the
SQLAlchemy metadata (the migrations are checked against it by `alembic check`).

    python -m app.cli.gen_docs ../docs
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from fastapi.routing import APIRoute
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

from app.core.config import Settings
from app.main import create_app
from app.models.base import Base

API_INTRO = """# API reference

Generated from the running application by `python -m app.cli.gen_docs` (do not edit by hand).
Base path `/api/v1`. Interactive docs: `/docs` (Swagger UI) and `/openapi.json` when the server runs.

* **Auth:** two steps. `/auth/register` or `/auth/login` sends a one-time SMS code (202, no tokens);
  `/auth/register/verify` or `/auth/login/verify` checks it and returns `Authorization: Bearer <access token>`;
  refresh with `/auth/refresh`.
* **Roles** below are the ones the route actually enforces (taken from its dependencies): `public`, `any signed-in`,
  or a role list. Resource routes additionally check ownership and answer **404** for another user's resource.
* **Errors** use one envelope: `{"error": {"code", "message", "details"}}`; 401 not signed in, 403 wrong role,
  404 not found / not yours, 409 state conflict, 422 validation or business rule, 503 provider unavailable.
* **Idempotency:** `POST /buyer-demands/{id}/pool` and `POST /orders` accept `Idempotency-Key`;
  `POST /pools/{id}/rebalance` requires it.
* **Data provenance:** responses label numbers as `measured`, `estimate`, `assumption` or `simulated`.
  No endpoint returns or computes a market price.
"""


def _leaves(routes: list[Any]) -> list[APIRoute]:
    """Every APIRoute, walking included routers (works across FastAPI's router representations)."""
    out: list[APIRoute] = []
    for r in routes:
        if isinstance(r, APIRoute):
            out.append(r)
        sub = getattr(r, "original_router", None) or getattr(r, "router", None)
        if sub is not None and sub is not r:
            out.extend(_leaves(list(getattr(sub, "routes", []))))
    return out


def _roles(route: APIRoute) -> str:
    found: list[str] = []

    def walk(dep: Any) -> None:
        call = getattr(dep, "call", None)
        qual = getattr(call, "__qualname__", "")
        if call is not None and "require_roles.<locals>.checker" in qual:
            closure = getattr(call, "__closure__", None) or ()
            cells = dict(zip(call.__code__.co_freevars, (c.cell_contents for c in closure), strict=False))
            found.append(", ".join(sorted(r.value for r in cells.get("roles", ()))))
        elif qual == "get_current_user":
            found.append("any signed-in")
        for sub in getattr(dep, "dependencies", []):
            walk(sub)

    walk(route.dependant)
    specific = [f for f in found if f != "any signed-in"]
    return specific[0] if specific else (found[0] if found else "public")


def _schema(ref: dict[str, Any] | None) -> str:
    if not ref:
        return ""
    if "$ref" in ref:
        return str(ref["$ref"]).split("/")[-1]
    if ref.get("type") == "array" and "items" in ref:
        return f"list[{_schema(ref['items'])}]"
    if "anyOf" in ref:
        return " | ".join(_schema(r) or r.get("type", "") for r in ref["anyOf"])
    return str(ref.get("type", ""))


def api_markdown() -> str:
    app = create_app(Settings(_env_file=None))
    spec = app.openapi()
    leaves = _leaves(list(app.routes))
    by_tag: dict[str, list[str]] = defaultdict(list)
    count = 0
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            if method not in ("get", "post", "patch", "put", "delete"):
                continue
            count += 1
            candidates = [
                r
                for r in leaves
                if method.upper() in (r.methods or set())
                and path.endswith(r.path)
                and str(op.get("operationId", "")).startswith(r.name)
            ]
            route = max(candidates, key=lambda r: len(r.path))
            body = op.get("requestBody", {}).get("content", {})
            req = ", ".join(f"{_schema(c.get('schema'))} ({ct.split('/')[-1]})" for ct, c in body.items())
            ok: dict[str, Any] = next((c for code, c in op.get("responses", {}).items() if code.startswith("2")), {})
            res = _schema(ok.get("content", {}).get("application/json", {}).get("schema")) or (
                "audio" if "speak" in path else "-"
            )
            tag = (op.get("tags") or ["other"])[0]
            short = path.replace("/api/v1", "")
            by_tag[tag].append(
                f"| `{method.upper()}` | `{short}` | {_roles(route)} | {req or '-'} | {res} | {op.get('summary', '')} |"
            )
    out = [API_INTRO, f"\n**{count} operations.**\n"]
    for tag in sorted(by_tag):
        out.append(f"\n## {tag}\n\n| Method | Path | Roles | Request | Response | Summary |\n|---|---|---|---|---|---|")
        out.extend(by_tag[tag])
    return "\n".join(out) + "\n"


DB_INTRO = """# Database

PostgreSQL 16, SQLAlchemy 2.0 models in `backend/app/models/`, Alembic migrations `0001_baseline` ->
`0007_marketplace`. Generated from the model metadata by `python -m app.cli.gen_docs` (do not edit by hand);
`alembic check` verifies the migrations produce exactly this schema (no drift).

Conventions: UUID primary keys; `created_at`/`updated_at` timestamps with time zone; quantities `NUMERIC(14,3)` kg;
enums stored as strings with CHECK constraints; foreign keys are `RESTRICT` unless stated, so audit history cannot be
deleted from under it. Append-only tables (never updated by the application): `yield_predictions`,
`calibration_profiles`, `reallocation_events`, `allocation_ledger`, `quality_checks`.

## Invariants enforced by the database (beyond the application)
* inventory: non-negative quantities; unique (lot, booking key) - no double booking
* pools: allocated within demand, one pool per demand, one allocation per (pool, lot), events account for every
  kilogram of shortage (`replaced + unresolved >= shortage`), unique event idempotency keys
* marketplace: one order per pool, one item and one participation per allocation, fulfilled <= ordered,
  fulfilled <= item quantity, unique batch codes, positive batch weight, one quality check per batch whose result
  matches its quantities (accepted / partially accepted / rejected)
* notifications: unique (user, dedup key) - the same event never notifies twice
"""


def db_markdown() -> str:
    out = [DB_INTRO, f"\n**{len(Base.metadata.tables)} tables.**\n"]
    for name in sorted(Base.metadata.tables):
        t = Base.metadata.tables[name]
        out.append(f"\n### `{name}`\n\n| Column | Type | Null | Notes |\n|---|---|---|---|")
        for c in t.columns:
            notes = []
            if c.primary_key:
                notes.append("PK")
            for fk in c.foreign_keys:
                notes.append(f"FK -> `{fk.column.table.name}` ({fk.ondelete or 'NO ACTION'})")
            if c.unique:
                notes.append("unique")
            if c.index:
                notes.append("indexed")
            out.append(f"| `{c.name}` | {c.type} | {'yes' if c.nullable else 'no'} | {', '.join(notes)} |")
        extras = []
        for con in t.constraints:
            if isinstance(con, UniqueConstraint) and len(con.columns) > 0:
                extras.append(f"UNIQUE ({', '.join(col.name for col in con.columns)})")
            elif isinstance(con, CheckConstraint):
                extras.append(f"CHECK `{con.name}`: `{str(con.sqltext)[:140]}`")
            elif isinstance(con, ForeignKeyConstraint):
                pass
        if extras:
            out.append("\nConstraints: " + "; ".join(sorted(set(extras))))
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> int:
    target = Path(argv[0] if argv else "../docs")
    (target / "API.md").write_text(api_markdown())
    (target / "DATABASE.md").write_text(db_markdown())
    print(f"wrote {target / 'API.md'} and {target / 'DATABASE.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
