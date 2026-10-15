"""Request ids, the per-request log line and safe 500s: what makes a failure on a phone traceable in the log."""

from __future__ import annotations

import json
import logging

from fastapi.testclient import TestClient

from app.core.logging import JsonFormatter
from app.main import create_app


def test_every_response_has_a_request_id_and_a_good_incoming_one_is_kept(client):
    r = client.get("/api/v1/health/ready")
    assert len(r.headers["x-request-id"]) == 16
    r = client.get("/api/v1/health/ready", headers={"X-Request-ID": "phone-abc12345"})
    assert r.headers["x-request-id"] == "phone-abc12345"
    r = client.get("/api/v1/health/ready", headers={"X-Request-ID": "bad id with spaces <script>"})
    assert r.headers["x-request-id"] != "bad id with spaces <script>"


def test_the_log_line_has_the_route_template_not_ids_or_query(client, caplog):
    caplog.set_level(logging.INFO, logger="harvestique.request")
    client.get("/api/v1/farms/0b8f8c1e-1111-2222-3333-444455556666?secret=x", headers={"X-Request-ID": "req-12345678"})
    rec = next(r for r in caplog.records if r.name == "harvestique.request")
    assert rec.path == "/api/v1/farms/{farm_id}" and rec.status == 401 and rec.request_id == "req-12345678"
    assert "secret" not in rec.getMessage() and "0b8f8c1e" not in rec.getMessage()


def test_an_unhandled_error_gives_a_safe_500_with_the_request_id(settings, container, caplog):
    app = create_app(settings=settings, container=container)

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("database password is hunter2")

    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/boom", headers={"X-Request-ID": "trace-0000001"})
    assert r.status_code == 500 and r.headers["x-request-id"] == "trace-0000001"
    body = r.json()["error"]
    assert body["code"] == "internal_error" and body["details"]["request_id"] == "trace-0000001"
    assert "hunter2" not in r.text
    assert any(rec.request_id == "trace-0000001" and rec.exc_info for rec in caplog.records)


def test_json_log_lines():
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "GET %s", ("/a",), None)
    rec.request_id, rec.status = "abc", 200
    out = json.loads(JsonFormatter().format(rec))
    assert out["msg"] == "GET /a" and out["request_id"] == "abc" and out["status"] == 200 and out["level"] == "INFO"
