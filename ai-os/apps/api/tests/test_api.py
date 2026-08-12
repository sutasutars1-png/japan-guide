"""Smoke tests for the Phase 1 API contract."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_agents_shape_matches_ui():
    r = client.get("/agents")
    assert r.status_code == 200
    agents = r.json()
    assert len(agents) == 5
    a = agents[0]
    assert {"id", "name", "model", "state", "caps", "role"} <= set(a)


def test_capabilities():
    r = client.get("/capabilities")
    body = r.json()
    assert "shell.execute" in body["capabilities"]
    assert "claude-opus-4-8" in body["models"]


def test_policy_check_endpoint_blocks():
    r = client.post("/execution/policy-check", json={"command": "rm -rf /"})
    assert r.json()["allowed"] is False


def test_demo_execution_is_available():
    r = client.get("/execution/demo")
    assert r.status_code == 200
    assert any(line["t"] == "halt" for line in r.json())


def test_tools_lists_shell():
    r = client.get("/tools")
    names = [t["name"] for t in r.json()]
    assert "shell.execute" in names


def test_llm_status_reports_provider_and_model():
    r = client.get("/llm")
    body = r.json()
    assert body["provider"] == "gemini"
    assert body["model"].startswith("gemini")
    assert isinstance(body["key_present"], bool)


def test_approval_flow():
    created = client.post(
        "/approvals",
        json={
            "agent": "Executor",
            "action": "Write to production database",
            "target": "pipeline-db",
            "risk": 4,
            "reason": "modifies live data",
            "changes": "upsert 1284 rows",
        },
    ).json()
    decided = client.post(f"/approvals/{created['id']}/decide", json={"approved": False})
    assert decided.json()["decision"] == "rejected"
