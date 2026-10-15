from app.providers.llm.fake import DisabledLLMProvider


def test_liveness(client):
    r = client.get("/api/v1/health/live")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_readiness_ok(client):
    r = client.get("/api/v1/health/ready")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"


def test_readiness_db_down_returns_503(client, container):
    container.db_ping = lambda: False
    r = client.get("/api/v1/health/ready")
    assert r.status_code == 503
    assert r.json()["status"] == "not_ready"


def test_llm_disabled_does_not_block_readiness(client, container):
    container.llm = DisabledLLMProvider()
    body = client.get("/api/v1/health/ready").json()
    assert body["status"] == "ready"
    assert {"name": "llm:disabled", "status": "disabled", "critical": False} in body["components"]


def test_openapi_available(client):
    assert client.get("/api/v1/openapi.json").status_code == 200


def test_unknown_route_404(client):
    assert client.get("/api/v1/nope").status_code == 404
