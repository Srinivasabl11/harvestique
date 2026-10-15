"""Repeatable end-to-end DEMO of the whole product, driven through the real HTTP API in-process.

    DATABASE_URL=.../harvestique_demo python -m app.cli.demo --reset

Flow: farmers -> farms -> crop plan -> predictions -> inventory -> buyer demand -> 2,000 kg pool -> order ->
farmer acceptance -> Farm C 450 -> 200 kg -> exact 250 kg shortage -> dynamic replacement (Farm F) -> harvests ->
collection -> quality -> fulfilment -> prediction feedback -> traceability.

Everything here is SIMULATED demo data: the `demo_scripted` provider echoes the farmer's estimate as an exact
quantity (labelled simulated), and the one price below is a farmer-entered demo input for the income plan only.
`--reset` deletes ALL rows, so it refuses any database whose name does not contain "demo".
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.composition import build_auth_service
from app.core.config import get_settings
from app.core.container import Container, build_container
from app.providers.prediction.demo import DemoScriptedPredictor
from app.providers.weather.fake import FakeWeatherProvider
from app.schemas.auth import AdminCreateRequest

API = "/api/v1"
PASSWORD = "Demo12345"  # noqa: S105 - published demo credential for a demo database only
ADMIN_PHONE = "+919000000100"
FARMS = {"A": 500, "B": 350, "C": 450, "D": 300, "E": 400}
REPLACEMENT_FARM = ("F", 300)
C_DROP_TO = 200
HARVESTS = {"A": 510, "B": 355, "C": 210, "D": 305, "E": 400, "F": 255}  # measured (demo), all >= commitments
QUALITY = {  # farm -> (grade, accepted share of received, rejected) ; demo inspection results
    "A": ("A", None, 0),
    "B": ("B", None, 10),
    "C": ("B", None, 0),
    "D": ("B", None, 0),
    "E": ("B", None, 5),
    "F": ("A", None, 0),
}
DEMO_FARMER_ENTERED_PRICE = {"low": 12, "expected": 15, "high": 18}  # INR/kg, farmer input for the income plan only


class DemoError(RuntimeError):
    pass


def _ok(resp: Any, expected: int = 200) -> Any:
    if resp.status_code != expected:
        raise DemoError(f"{resp.request.method} {resp.request.url.path} -> {resp.status_code}: {resp.text[:300]}")
    return resp.json() if resp.content else None


def run_demo(client: Any, container: Container, log: Callable[[str], None] = print) -> dict[str, Any]:
    """Run the scripted scenario. `client` is an HTTP client bound to the app (e.g. Starlette TestClient)."""
    today = date.today()

    def d(n: int) -> str:
        return (today + timedelta(days=n)).isoformat()

    def register(body: dict[str, Any]) -> None:
        _ok(client.post(f"{API}/auth/register", json=body), 201)  # the demo server keeps open sign-up

    def login(phone: str) -> dict[str, str]:
        tokens = _ok(client.post(f"{API}/auth/login", json={"phone": phone, "password": PASSWORD}))["tokens"]
        return {"Authorization": f"Bearer {tokens['access_token']}"}

    # 1. accounts, crop, hub ------------------------------------------------------------------------------
    with container.session_factory() as session:
        build_auth_service(session, container).create_admin(
            AdminCreateRequest(phone=ADMIN_PHONE, password=PASSWORD, full_name="Demo Hub Admin")
        )
    admin = login(ADMIN_PHONE)
    crop = _ok(
        client.post(
            f"{API}/crops",
            headers=admin,
            json={"name": "Tomato", "category": "vegetable", "typical_duration_days": 100},
        ),
        201,
    )
    hub = _ok(
        client.post(
            f"{API}/admin/hubs",
            headers=admin,
            json={"name": "Mysuru Demo Hub", "district": "Mysuru", "latitude": 12.30, "longitude": 76.64},
        ),
        201,
    )
    log(f"[1] admin, crop Tomato and hub '{hub['name']}' ready")

    farmers: dict[str, dict[str, Any]] = {}

    def add_farmer(name: str, kg: int, idx: int, *, opt_in: bool) -> dict[str, Any]:
        phone = f"90000001{idx:02d}"
        body = {
            "role": "farmer",
            "phone": phone,
            "password": PASSWORD,
            "full_name": f"Demo Farmer {name}",
            "profile": {"district": "Mysuru", "preferred_language": "kn" if name in "CF" else "en"},
        }
        register(body)
        h = login(phone)
        farm = _ok(
            client.post(
                f"{API}/farms",
                headers=h,
                json={
                    "name": f"Farm {name}",
                    "total_area_acres": 3,
                    "latitude": round(12.30 + idx / 100, 4),
                    "longitude": 76.64,
                },
            ),
            201,
        )
        plot = _ok(
            client.post(
                f"{API}/farms/{farm['id']}/plots",
                headers=h,
                json={"name": "Main plot", "area_acres": 2, "irrigation_type": "drip"},
            ),
            201,
        )
        cycle = _ok(
            client.post(
                f"{API}/plots/{plot['id']}/crop-cycles",
                headers=h,
                json={
                    "crop_id": crop["id"],
                    "status": "growing",
                    "area_acres": 1,
                    "sowing_date": d(-60),
                    "expected_harvest_date": d(40),
                },
            ),
            201,
        )
        info = {"h": h, "farm": farm, "cycle": cycle, "kg": kg}
        info["prediction"] = predict(info, kg)
        lot = next(
            x for x in _ok(client.get(f"{API}/inventory/lots", headers=h))["items"] if x["crop_cycle_id"] == cycle["id"]
        )
        info["lot"] = _ok(
            client.patch(
                f"{API}/inventory/lots/{lot['id']}", headers=h, json={"pool_eligible": opt_in, "expected_grade": "B"}
            )
        )
        farmers[name] = info
        return info

    def predict(info: dict[str, Any], kg: int) -> Any:
        est = {"low": kg, "expected": kg, "high": kg}
        return _ok(
            client.post(
                f"{API}/crop-cycles/{info['cycle']['id']}/predictions",
                headers=info["h"],
                json={"farmer_estimate_per_acre": est},
            ),
            201,
        )

    for i, (name, kg) in enumerate(FARMS.items(), start=1):
        add_farmer(name, kg, i, opt_in=True)
    log(
        "[2] farmers A-E: farm, plot, growing tomato, prediction, lot opted into pooling: "
        + ", ".join(f"{n} {farmers[n]['lot']['available_kg']:g} kg" for n in FARMS)
    )

    a = farmers["A"]
    plan = _ok(
        client.post(f"{API}/crop-plans", headers=a["h"], json={"name": "Rabi tomato plan", "farm_id": a["farm"]["id"]}),
        201,
    )
    item = _ok(
        client.post(
            f"{API}/crop-plans/{plan['id']}/items/from-prediction",
            headers=a["h"],
            json={"prediction_id": a["prediction"]["id"], "price_per_kg": DEMO_FARMER_ENTERED_PRICE},
        ),
        201,
    )
    log(
        f"[3] Farm A income plan built from its prediction ({len(item.get('items', [])) or 1} item; demo farmer-entered price)"
    )

    # 2. buyer, demand, pool, order -----------------------------------------------------------------------
    register(
        {
            "role": "buyer",
            "phone": "9000000199",
            "password": PASSWORD,
            "full_name": "Demo Buyer",
            "profile": {"business_name": "Mysuru Fresh Mart", "buyer_type": "retailer"},
        }
    )
    buyer = login("9000000199")
    demand = _ok(
        client.post(
            f"{API}/buyer-demands",
            headers=buyer,
            json={
                "crop_id": crop["id"],
                "quantity_kg": 2000,
                "window_start": d(20),
                "window_end": d(90),
                "min_grade": "B",
            },
        ),
        201,
    )
    pool = _ok(
        client.post(
            f"{API}/buyer-demands/{demand['id']}/pool", headers={**buyer, "Idempotency-Key": "demo-pool"}, json={}
        ),
        201,
    )
    log(
        f"[4] demand 2,000 kg -> pool {pool['status']} with {pool['allocated_kg']:g} kg from {len(pool['allocations'])} farms (algorithm: {pool['algorithm']})"
    )
    order = _ok(
        client.post(
            f"{API}/orders",
            headers={**buyer, "Idempotency-Key": "demo-order"},
            json={"pool_id": pool["id"], "delivery_hub_id": hub["id"]},
        ),
        201,
    )
    accept_all(client, farmers)
    order = _ok(client.get(f"{API}/orders/{order['id']}", headers=buyer))
    log(f"[5] order placed; every farmer accepted -> order {order['status']}")

    # 3. a new farm joins, then Farm C's prediction falls --------------------------------------------------
    add_farmer(REPLACEMENT_FARM[0], REPLACEMENT_FARM[1], 6, opt_in=True)
    farmers["C"]["prediction"] = predict(farmers["C"], C_DROP_TO)
    events = _ok(client.get(f"{API}/pools/{pool['id']}/events", headers=buyer))
    event = events[-1]
    log(
        f"[6] Farm C 450 -> {C_DROP_TO} kg: shortage {event['shortage_kg']:g} kg, replaced {event['replaced_kg']:g} kg, unresolved {event['unresolved_kg']:g} kg ({event['outcome']})"
    )
    accept_all(client, farmers)
    order = _ok(client.get(f"{API}/orders/{order['id']}", headers=buyer))
    log(f"[7] replacement farm F accepted; order {order['status']}, committed {order['committed_kg']:g} kg")

    # 4. harvest, collection, quality, fulfilment --------------------------------------------------------
    for name, info in farmers.items():
        _ok(
            client.patch(
                f"{API}/crop-cycles/{info['cycle']['id']}",
                headers=info["h"],
                json={"status": "harvested", "actual_harvest_date": d(0)},
            )
        )
        _ok(
            client.post(
                f"{API}/crop-cycles/{info['cycle']['id']}/harvest-actual",
                headers=info["h"],
                json={"quantity_kg": HARVESTS[name]},
            ),
            201,
        )
    log("[8] harvests recorded (measured): " + ", ".join(f"{n} {HARVESTS[n]} kg" for n in farmers))
    lot_name = {info["lot"]["id"]: n for n, info in farmers.items()}
    order = _ok(client.get(f"{API}/orders/{order['id']}", headers=buyer))
    received: dict[str, Any] = {}
    for it in sorted(order["items"], key=lambda x: lot_name[x["lot_id"]]):  # stable, readable order
        if it["status"] != "accepted":
            continue
        name = lot_name[it["lot_id"]]
        batch = _ok(
            client.post(
                f"{API}/admin/batches",
                headers=admin,
                json={"order_item_id": it["id"], "hub_id": hub["id"], "received_kg": it["quantity_kg"]},
            ),
            201,
        )
        grade, _share, rejected = QUALITY[name]
        q = {"grade": grade, "accepted_kg": it["quantity_kg"] - rejected, "rejected_kg": rejected}
        received[name] = _ok(client.post(f"{API}/admin/batches/{batch['id']}/quality", headers=admin, json=q))
        _ok(client.post(f"{API}/admin/order-items/{it['id']}/fulfil", headers=admin))
    log(
        "[9] batches received, quality-checked and fulfilled: "
        + ", ".join(f"{n} {b['code']} ({b['quality']['result']})" for n, b in received.items())
    )
    order = _ok(client.get(f"{API}/orders/{order['id']}", headers=buyer))
    log(
        f"[10] order {order['status']}: {order['fulfilled_kg']:g} of {order['ordered_kg']:g} kg delivered (quality rejects are not counted)"
    )

    # 5. prediction feedback and traceability ----------------------------------------------------------
    fb = _ok(client.get(f"{API}/crop-cycles/{farmers['C']['cycle']['id']}/feedback", headers=farmers["C"]["h"]))
    trace = _ok(client.get(f"{API}/orders/{order['id']}/trace", headers=buyer))
    scored = [(f["prediction_version"], f["predicted"]["p50"], f["abs_pct_error"]) for f in fb["feedback"]]
    log(
        f"[11] Farm C prediction feedback vs measured {fb['actual']['quantity_kg']:g} kg: "
        + "; ".join(f"v{v} predicted {p:g} kg, error {e}%" for v, p, e in scored)
        + f"; trace covers {len(trace['items'])} farm items"
    )
    return {
        "pool_id": pool["id"],
        "order_id": order["id"],
        "initial_allocation_kg": pool["allocated_kg"],
        "shortage_kg": event["shortage_kg"],
        "replaced_kg": event["replaced_kg"],
        "unresolved_kg": event["unresolved_kg"],
        "reallocation_outcome": event["outcome"],
        "order_status": order["status"],
        "ordered_kg": order["ordered_kg"],
        "fulfilled_kg": order["fulfilled_kg"],
        "batches": {n: b["code"] for n, b in received.items()},
        "farm_c_feedback": scored,
        "trace_steps": sorted({s["step"] for i in trace["items"] for s in i["steps"]}),
        "data_note": "SIMULATED demo data (scripted predictions, demo harvest and quality figures).",
    }


def accept_all(client: Any, farmers: dict[str, dict[str, Any]]) -> None:
    for info in farmers.values():
        page = _ok(client.get(f"{API}/participations", headers=info["h"], params={"status": "pending"}))
        for p in page["items"]:
            _ok(client.post(f"{API}/participations/{p['id']}/accept", headers=info["h"]))


def reset_database(container: Container) -> None:
    name = make_url(container.settings.database_url).database or ""
    if "demo" not in name:
        raise DemoError(f"Refusing to reset database '{name}': its name must contain 'demo'")
    with container.engine.begin() as conn:
        tables = [
            r[0]
            for r in conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version'")
            )
        ]
        if tables:
            conn.execute(text("TRUNCATE " + ", ".join(f'"{t}"' for t in tables) + " RESTART IDENTITY CASCADE"))


def main(argv: Sequence[str] | None = None) -> int:
    from fastapi.testclient import TestClient

    from app.main import create_app

    parser = argparse.ArgumentParser(description="Run the repeatable Harvestique demo (simulated data)")
    parser.add_argument(
        "--reset", action="store_true", help="delete all rows first (database name must contain 'demo')"
    )
    parser.add_argument("--json", action="store_true", help="print the summary as JSON")
    args = parser.parse_args(argv)
    # The scenario creates its own scripted crop (step 1); the startup catalog seed would make that a 409.
    # Open sign-up: the demo accounts are used at once, without an admin approving each one.
    settings = get_settings().model_copy(
        update={"seed_crop_catalog_on_startup": False, "new_account_access": "approved"}
    )
    container = build_container(settings)
    container.predictor = DemoScriptedPredictor()  # scripted, labelled SIMULATED
    container.weather = FakeWeatherProvider()  # deterministic offline weather for a repeatable demo
    try:
        if args.reset:
            reset_database(container)
        with TestClient(create_app(settings=settings, container=container)) as client:
            summary = run_demo(client, container)
        if args.json:
            print(json.dumps(summary, indent=2, default=str))
        return 0
    except DemoError as exc:
        print(f"demo failed: {exc}", file=sys.stderr)
        return 1
    finally:
        container.shutdown()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
