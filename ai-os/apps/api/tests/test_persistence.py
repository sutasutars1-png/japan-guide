"""Persistence expansion — connections' model lists, custom presets, custom flows
survive via git-ignored JSON stores. Seed presets/flows stay read-only."""
import os

os.environ.setdefault("AIOS_ALLOW_UNSAFE_LOCAL", "1")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import connections, flow as flow_mod, presets  # noqa: E402
from app.json_store import load_json, save_json  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setenv("AIOS_ENV_FILE", str(tmp_path / ".env"))
    presets.reset_to_seed()
    flow_mod.reset_to_seed()
    yield
    presets.reset_to_seed()
    flow_mod.reset_to_seed()


# ---- json_store ------------------------------------------------------------

def test_json_store_roundtrip_and_default():
    save_json(".aios-test.json", {"a": 1, "b": ["x"]})
    assert load_json(".aios-test.json", None) == {"a": 1, "b": ["x"]}
    assert load_json(".aios-missing.json", "fallback") == "fallback"


# ---- connections: manual model list persists -------------------------------

def test_manual_model_persists_and_removes():
    connections.add_manual_model("claude-web", "persist-me")
    saved = load_json(".aios-connections.json", {})
    assert "persist-me" in saved.get("claude-web", [])
    # visible through the API
    assert any(m["model"] == "persist-me" for m in client.get("/models").json())
    connections.remove_manual_model("claude-web", "persist-me")
    saved2 = load_json(".aios-connections.json", {})
    assert "persist-me" not in saved2.get("claude-web", [])


def test_manual_model_delete_endpoint():
    client.post("/connections/claude-web/models", json={"model": "ep-model"})
    assert any(m["model"] == "ep-model" for m in client.get("/models").json())
    r = client.request("DELETE", "/connections/claude-web/models", json={"model": "ep-model"})
    assert r.status_code == 200
    assert not any(m["model"] == "ep-model" for m in client.get("/models").json())
    connections.remove_manual_model("claude-web", "ep-model")  # ensure clean


# ---- presets CRUD ----------------------------------------------------------

def test_preset_crud_and_seed_is_read_only():
    created = client.post("/presets", json={"name": "私の束", "stage": "Builder", "skills": ["BASE-SYS"]})
    assert created.status_code == 201
    pid = created.json()["id"]
    assert pid.startswith("custom.")
    assert any(p["id"] == pid for p in client.get("/presets").json())

    up = client.put(f"/presets/{pid}", json={"name": "改", "stage": "Builder", "skills": ["BASE-SYS", "DOM-SW"]})
    assert up.status_code == 200 and up.json()["name"] == "改"
    assert pid in [p["id"] for p in load_json(".aios-presets.json", [])]  # persisted

    # seed presets are read-only
    assert client.put("/presets/preset.builder", json={"name": "x", "stage": "Builder", "skills": []}).status_code == 400
    assert client.delete("/presets/preset.builder").status_code == 400

    assert client.delete(f"/presets/{pid}").status_code == 204
    assert not any(p["id"] == pid for p in client.get("/presets").json())


def test_custom_preset_survives_reload():
    p = presets.add_preset("再読込", "Reviewer", ["BASE-EVAL"])
    # a fresh load from disk (simulates a restart) sees it
    assert any(x["id"] == p["id"] for x in presets._load_custom())


# ---- flows CRUD ------------------------------------------------------------

def test_flow_crud_and_seed_is_read_only():
    body = {"name": "調査フロー", "max_iterations": 5,
            "stations": [{"agent": "Researcher", "next": "Builder"}, {"agent": "Builder", "next": "DONE"}]}
    created = client.post("/flows", json=body)
    assert created.status_code == 201
    fid = created.json()["id"]
    assert fid.startswith("flow.custom.")
    assert any(f["id"] == fid for f in client.get("/flows").json())

    up = client.put(f"/flows/{fid}", json={**body, "name": "調査フロー改"})
    assert up.status_code == 200 and up.json()["name"] == "調査フロー改"

    # seed flows read-only; empty stations rejected
    assert client.put("/flows/flow.default", json=body).status_code == 400
    assert client.delete("/flows/flow.default").status_code == 400
    assert client.post("/flows", json={"name": "空", "stations": []}).status_code == 400

    assert client.delete(f"/flows/{fid}").status_code == 204
    assert not any(f["id"] == fid for f in client.get("/flows").json())


def test_custom_flow_survives_reload_and_is_runnable_target():
    f = flow_mod.add_flow("単発", [{"agent": "Builder", "next": "DONE"}], max_iterations=3)
    assert any(x["id"] == f["id"] for x in flow_mod._load_custom())  # persisted
    assert flow_mod.get_flow(f["id"]) is not None                    # resolvable by the runner
