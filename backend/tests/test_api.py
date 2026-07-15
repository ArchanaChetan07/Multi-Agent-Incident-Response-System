import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # Isolate persistence per test run
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    # Reload config-dependent modules so the new DB_PATH takes effect
    import importlib
    from backend.app import config
    importlib.reload(config)
    from backend.app import main
    importlib.reload(main)
    return TestClient(main.app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_ready(client):
    r = client.get("/ready")
    assert r.status_code == 200


def test_list_incidents_includes_seed_data(client):
    r = client.get("/incidents")
    assert r.status_code == 200
    ids = [i["id"] for i in r.json()]
    assert "INC-001" in ids
    assert "TRAP-001" in ids


def test_investigate_unknown_incident_404s(client):
    r = client.post("/incidents/DOES-NOT-EXIST/investigate")
    assert r.status_code == 404


def test_report_before_investigation_404s(client):
    r = client.get("/incidents/INC-001/report")
    assert r.status_code == 404


def test_report_returns_cached_result_not_a_rerun(client):
    """Regression test: /report must NOT re-run the pipeline — it should
    return the exact result of the last /investigate call."""
    inv = client.post("/incidents/INC-001/investigate")
    assert inv.status_code == 200
    inv_body = inv.json()

    rep = client.get("/incidents/INC-001/report")
    assert rep.status_code == 200
    rep_body = rep.json()

    assert rep_body["root_cause"] == inv_body["root_cause"]
    assert rep_body["cost_usd"] == inv_body["cost_usd"]
    # Cost should NOT double from calling /report afterward
    rep2 = client.get("/incidents/INC-001/report")
    assert rep2.json()["cost_usd"] == inv_body["cost_usd"]


def test_create_incident_and_investigate(client):
    payload = {
        "id": "CUSTOM-001",
        "logs": ["ERROR test failure"],
        "stack_traces": [],
        "pr_diffs": [],
        "timeline": [],
    }
    r = client.post("/incidents", json=payload)
    assert r.status_code == 200

    r2 = client.post("/incidents", json=payload)
    assert r2.status_code == 409  # duplicate

    r3 = client.post("/incidents/CUSTOM-001/investigate")
    assert r3.status_code == 200


def test_create_incident_rejects_oversized_payload(client):
    payload = {"id": "BIG-001", "logs": ["x" * 999999]}
    r = client.post("/incidents", json=payload)
    assert r.status_code == 422


def test_auth_enforced_when_token_set(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test2.db"))
    monkeypatch.setenv("API_AUTH_TOKEN", "secret123")
    import importlib
    from backend.app import config
    importlib.reload(config)
    from backend.app import main
    importlib.reload(main)
    c = TestClient(main.app)

    r = c.post("/incidents/INC-001/investigate")
    assert r.status_code == 401

    r2 = c.post("/incidents/INC-001/investigate", headers={"Authorization": "Bearer secret123"})
    assert r2.status_code == 200
