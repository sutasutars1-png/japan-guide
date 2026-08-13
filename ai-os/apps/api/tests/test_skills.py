"""Layered skill library tests — DB integrity, endpoints, composition."""
from fastapi.testclient import TestClient

from app import seed, skills
from app.main import app

client = TestClient(app)


# ---- database integrity ----

def test_skill_ids_are_unique():
    ids = [s["id"] for s in skills.SKILLS]
    assert len(ids) == len(set(ids))


def test_every_skill_has_a_valid_layer():
    for s in skills.SKILLS:
        assert s["layer"] in skills.LAYERS, f"{s['id']} has bad layer {s['layer']}"


def test_roles_are_valid_stages():
    for s in skills.SKILLS:
        for r in s.get("roles", []):
            assert r in skills.STAGES, f"{s['id']} references unknown stage {r}"


def test_layer_counts():
    by = lambda ly: len(skills.list_skills(layer=ly))
    assert by("thinking") == 5      # 5 thinking modes
    assert by("domain") == 25       # 25 domain lenses
    assert by("execution") >= 8
    assert by("overlay") >= 12


def test_every_agent_base_skill_exists():
    for stage, ids in skills.AGENT_BASE_SKILLS.items():
        assert stage in skills.STAGES
        for sid in ids:
            assert skills.get_skill(sid) is not None, f"{stage} references missing skill {sid}"


def test_seed_agents_match_base_skills():
    for a in seed.AGENTS:
        assert a.get("skills") == skills.AGENT_BASE_SKILLS.get(a["name"]), a["name"]


# ---- endpoints ----

def test_list_skills_endpoint_and_layer_filter():
    assert any(s["id"] == "BASE-SYS" for s in client.get("/skills").json())
    domains = client.get("/skills", params={"layer": "domain"}).json()
    assert len(domains) == 25
    assert all(s["layer"] == "domain" for s in domains)


def test_role_filter_includes_universal_skills():
    # exec.safe_report has roles=all stages; OVR-OPT-MIN too → appear for Builder
    ids = [s["id"] for s in client.get("/skills", params={"role": "Builder"}).json()]
    assert "DOM-SW" in ids            # Builder-suggested domain
    assert "exec.safe_report" in ids  # universal


def test_layers_and_get_single_and_404():
    assert set(client.get("/skills/layers").json()) == set(skills.LAYERS)
    assert client.get("/skills/BASE-ANA").json()["layer"] == "thinking"
    assert client.get("/skills/nope").status_code == 404


def test_agents_endpoint_includes_layered_skills():
    agents = client.get("/agents").json()
    builder = next(a for a in agents if a["name"] == "Builder")
    assert "DOM-SW" in builder["skills"]
    assert "exec.small_steps" in builder["skills"]


# ---- composition ----

def test_compose_system_is_layered_and_ordered():
    sys = skills.compose_system("Builder")
    assert sys is not None
    # role text + section headers, in layer order
    assert "# 役割（工程）" in sys
    assert "Verify with tests" in sys                 # role text
    assert "# 思考モード — 設計・構造化" in sys        # thinking (BASE-SYS)
    assert "# 専門レンズ — ソフトウェアエンジニア" in sys  # domain (DOM-SW)
    assert "# 実行の手順" in sys                       # execution group
    assert "python -c" in sys                          # exec.small_steps content
    # thinking section must come before the execution section
    assert sys.index("# 思考モード") < sys.index("# 実行の手順")


def test_compose_system_reviewer_includes_overlay():
    sys = skills.compose_system("Reviewer")
    assert "# 追加の方針" in sys        # overlay group (OVR-GOV-SEC)
    assert "OWASP" in sys


def test_compose_system_custom_ids():
    sys = skills.compose_system("Builder", skill_ids=["BASE-GEN", "OVR-OPT-MIN"])
    assert "# 思考モード — 構想・生成" in sys
    assert "最短の文字数" in sys        # OVR-OPT-MIN content


def test_compose_system_unknown_agent_is_none():
    assert skills.compose_system("Nobody", skill_ids=[]) is None
