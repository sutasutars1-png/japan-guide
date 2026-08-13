"""Presets + agent store: apply / reset, and the loop reading current skills."""
from fastapi.testclient import TestClient

from app import agents_store, presets, skills
from app.main import app

client = TestClient(app)


def test_default_presets_match_base_skills():
    for stage, pid in presets.AGENT_DEFAULT_PRESET.items():
        p = presets.get_preset(pid)
        assert p is not None and p["skills"] == skills.AGENT_BASE_SKILLS[stage]


def test_list_presets_and_stage_filter():
    assert any(p["id"] == "preset.builder_data" for p in client.get("/presets").json())
    builder = client.get("/presets", params={"stage": "Builder"}).json()
    assert {p["id"] for p in builder} == {"preset.builder", "preset.builder_data"}


def test_apply_then_reset_preset():
    a = agents_store.get_by_name("Builder")
    original = list(a["skills"])
    try:
        # apply the data-analysis preset
        r = client.post(f"/agents/{a['id']}/apply-preset", json={"preset_id": "preset.builder_data"})
        assert r.status_code == 200
        assert "DOM-DATA" in r.json()["skills"]
        assert r.json()["preset"] == "preset.builder_data"
        # the store (what the loop reads) reflects it
        assert "DOM-DATA" in agents_store.skills_for("Builder")
        # reset restores the active preset's skills
        r2 = client.post(f"/agents/{a['id']}/reset-preset")
        assert r2.status_code == 200
        assert r2.json()["skills"] == presets.get_preset("preset.builder_data")["skills"]
    finally:
        # restore original for other tests (apply back the web/general preset)
        client.post(f"/agents/{a['id']}/apply-preset", json={"preset_id": "preset.builder"})
        assert agents_store.skills_for("Builder") == original


def test_apply_unknown_preset_404():
    a = agents_store.get_by_name("Reviewer")
    assert client.post(f"/agents/{a['id']}/apply-preset", json={"preset_id": "nope"}).status_code == 404


def test_edit_skills_persists_to_store_and_composes():
    # editing an agent (PUT) updates the store, which the loop composes from
    a = dict(agents_store.get_by_name("Planner"))
    edited = dict(a)
    edited["skills"] = a["skills"] + ["DOM-LEG"]
    try:
        r = client.put(f"/agents/{a['id']}", json=edited)
        assert r.status_code == 200
        composed = skills.compose_system("Planner", skill_ids=agents_store.skills_for("Planner"))
        assert "専門レンズ — 法務・コンプライアンス" in composed
    finally:
        client.put(f"/agents/{a['id']}", json=a)
