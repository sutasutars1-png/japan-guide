"""Skill library tests — DB integrity, endpoints, and prompt composition."""
from fastapi.testclient import TestClient

from app import seed, skills
from app.main import app

client = TestClient(app)


# ---- database integrity ----

def test_skill_ids_are_unique():
    ids = [s["id"] for s in skills.SKILLS]
    assert len(ids) == len(set(ids))


def test_skill_roles_are_valid():
    for s in skills.SKILLS:
        assert s["roles"], f"{s['id']} has no roles"
        for r in s["roles"]:
            assert r in skills.ROLES, f"{s['id']} references unknown role {r}"


def test_every_agent_base_skill_exists():
    for role, ids in skills.AGENT_BASE_SKILLS.items():
        assert role in skills.ROLES
        for sid in ids:
            assert skills.get_skill(sid) is not None, f"{role} references missing skill {sid}"


def test_seed_agents_match_base_skills():
    # the /agents seed and the skills-lib base map must agree
    for a in seed.AGENTS:
        assert a.get("skills") == skills.AGENT_BASE_SKILLS.get(a["name"]), a["name"]


# ---- endpoints ----

def test_list_skills_endpoint():
    r = client.get("/skills")
    assert r.status_code == 200
    assert any(s["id"] == "build.small_steps" for s in r.json())


def test_list_skills_filtered_by_role():
    r = client.get("/skills", params={"role": "Reviewer"})
    ids = [s["id"] for s in r.json()]
    assert "review.read_only" in ids
    assert "plan.decompose" not in ids  # Planner-only skill excluded


def test_get_single_skill_and_404():
    assert client.get("/skills/plan.decompose").json()["name"] == "ゴール分解"
    assert client.get("/skills/nope").status_code == 404


def test_agents_endpoint_includes_skills():
    agents = client.get("/agents").json()
    builder = next(a for a in agents if a["name"] == "Builder")
    assert "build.small_steps" in builder["skills"]


# ---- composition ----

def test_compose_system_includes_role_and_skill_content():
    sys = skills.compose_system("Builder")
    assert sys is not None
    assert "Verify with tests" in sys              # role text
    assert "小さく実行" in sys                       # a skill name
    assert "python -c" in sys                       # a skill's content
    assert "# スキル（この役割の手順）" in sys


def test_compose_system_unknown_agent_is_none():
    assert skills.compose_system("Nobody") is None
