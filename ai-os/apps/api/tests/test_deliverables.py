"""Deliverables tests — store, rendering/export, log reconstruction, endpoints,
and the orchestrator auto-save. No network."""
import os

os.environ.setdefault("AIOS_ALLOW_UNSAFE_LOCAL", "1")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import deliverables  # noqa: E402
from app.agent_loop import AgentLoop  # noqa: E402
from app.core.llm.base import LLMResponse, LLMUsage  # noqa: E402
from app.core.sandbox.local_runtime import LocalSubprocessRuntime  # noqa: E402
from app.execution_manager import ExecutionManager, LogLine  # noqa: E402
from app.main import app  # noqa: E402
from app.orchestrator import OrchestratorRunner  # noqa: E402

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    # persist to a throwaway file and start each test with an empty store
    monkeypatch.setenv("AIOS_ENV_FILE", str(tmp_path / ".env"))
    deliverables.clear()
    yield
    deliverables.clear()


class FakeProvider:
    name = "fake"

    def __init__(self, reply):
        self._replies = list(reply) if isinstance(reply, list) else None
        self._reply = reply
        self._i = 0

    async def complete(self, messages, *, model, tools=None, max_tokens=1024):
        if self._replies is not None:
            text = self._replies[min(self._i, len(self._replies) - 1)]
            self._i += 1
        else:
            text = self._reply
        return LLMResponse(text=text, usage=LLMUsage(input_tokens=1, output_tokens=1))


# ---- store + export ---------------------------------------------------------

def test_save_lists_and_gets_roundtrip():
    item = deliverables.save(
        goal="レポートを作る",
        artifacts=[{"agent": "Builder", "task": "書く", "content": "本文"}],
    )
    assert item["id"].startswith("dlv_")
    meta = deliverables.list_deliverables()
    assert len(meta) == 1 and meta[0]["artifact_count"] == 1
    assert "artifacts" not in meta[0]  # list view is metadata only
    full = deliverables.get(item["id"])
    assert full["artifacts"][0]["content"] == "本文"


def test_save_drops_empty_artifacts():
    item = deliverables.save(goal="g", artifacts=[
        {"agent": "A", "task": "t", "content": "  "},
        {"agent": "B", "task": "t", "content": "keep"},
    ])
    assert len(item["artifacts"]) == 1
    assert item["artifacts"][0]["agent"] == "B"


def test_render_markdown_has_title_goal_and_sections():
    item = deliverables.save(goal="集計する", orchestrator="Planner", artifacts=[
        {"agent": "Builder", "task": "実装", "content": "コード"},
        {"agent": "Reviewer", "task": "確認", "content": "OK"},
    ])
    md = deliverables.render_markdown(item)
    assert "集計する" in md
    assert "## 1. Builder — 実装" in md
    assert "## 2. Reviewer — 確認" in md
    assert "Planner" in md


def test_export_formats():
    item = deliverables.save(goal="タイトル", artifacts=[{"agent": "A", "task": "", "content": "x"}])
    md, mtype, fname = deliverables.export(item, "md")
    assert fname.endswith(".md") and "markdown" in mtype and "# " in md
    txt, _, fname_t = deliverables.export(item, "txt")
    assert fname_t.endswith(".txt") and "#" not in txt.splitlines()[0]
    js, jtype, fname_j = deliverables.export(item, "json")
    assert fname_j.endswith(".json") and "application/json" in jtype
    with pytest.raises(ValueError):
        deliverables.export(item, "pdf")


def test_bounded_to_max():
    for i in range(deliverables.MAX_DELIVERABLES + 5):
        deliverables.save(goal=f"g{i}", artifacts=[{"agent": "A", "task": "", "content": str(i)}])
    assert len(deliverables.list_deliverables()) == deliverables.MAX_DELIVERABLES


# ---- reconstruct from log lines --------------------------------------------

def test_artifacts_from_lines_groups_by_step():
    lines = [
        {"t": "sys", "s": "統括AI 思考中…"},
        {"t": "sys", "s": "▶ 工程 1: Builder — 実装して"},
        {"t": "out", "s": "[Builder] 一行目"},
        {"t": "out", "s": "[Builder] 二行目"},
        {"t": "sys", "s": "▶ 工程 2: Reviewer — 確認して"},
        {"t": "out", "s": "[Reviewer] 合格"},
        {"t": "ok", "s": "オーケストレーション完了 ✓"},
    ]
    arts = deliverables.artifacts_from_lines(lines)
    assert [a["agent"] for a in arts] == ["Builder", "Reviewer"]
    assert arts[0]["task"] == "実装して"
    assert "一行目" in arts[0]["content"] and "二行目" in arts[0]["content"]
    assert "オーケストレーション完了" not in arts[1]["content"]


# ---- endpoints --------------------------------------------------------------

def test_endpoints_save_download_delete():
    saved = client.post("/deliverables", json={
        "goal": "エンドポイント確認", "source": "manual",
        "artifacts": [{"agent": "Builder", "task": "作る", "content": "成果"}],
    })
    assert saved.status_code == 200
    did = saved.json()["id"]

    assert any(d["id"] == did for d in client.get("/deliverables").json())
    assert client.get(f"/deliverables/{did}").json()["artifacts"][0]["content"] == "成果"

    dl = client.get(f"/deliverables/{did}/download", params={"format": "md"})
    assert dl.status_code == 200
    assert "attachment" in dl.headers["content-disposition"]
    assert "エンドポイント確認" in dl.text

    assert client.delete(f"/deliverables/{did}").status_code == 204
    assert client.get(f"/deliverables/{did}").status_code == 404


def test_save_from_lines_endpoint():
    r = client.post("/deliverables", json={
        "goal": "ログから復元", "source": "flow",
        "lines": [
            {"t": "sys", "s": "▶ 工程 1: Builder — 作業"},
            {"t": "out", "s": "[Builder] できました"},
        ],
    })
    assert r.status_code == 200
    assert r.json()["artifacts"][0]["content"] == "できました"


def test_save_empty_is_rejected():
    r = client.post("/deliverables", json={"goal": "空", "artifacts": [], "lines": []})
    assert r.status_code == 400


def test_download_unknown_format_400():
    saved = client.post("/deliverables", json={
        "goal": "g", "artifacts": [{"agent": "A", "task": "", "content": "x"}]})
    did = saved.json()["id"]
    assert client.get(f"/deliverables/{did}/download", params={"format": "pdf"}).status_code == 400


# ---- orchestrator auto-save -------------------------------------------------

def _spy_runner(plan_text):
    class SpyLoop:
        async def run(self, goal, *, agent_name, system=None, max_iterations=6):
            yield LogLine("ok", "agent finished ✓")
            yield LogLine("out", f"{agent_name} の成果物")

    return OrchestratorRunner(loop=SpyLoop(), provider=FakeProvider(plan_text))


async def test_orchestrate_autosaves_deliverable():
    runner = _spy_runner("Builder: A\nReviewer: B\nDONE")
    lines = [(l.t, l.s) async for l in runner.run("ゴール", orchestrator="Planner")]
    joined = "\n".join(s for _, s in lines)
    assert "成果物を保存しました" in joined
    saved = deliverables.list_deliverables()
    assert len(saved) == 1
    full = deliverables.get(saved[0]["id"])
    assert [a["agent"] for a in full["artifacts"]] == ["Builder", "Reviewer"]
    assert full["source"] == "orchestrate" and full["status"] == "complete"


async def test_orchestrate_no_deliverable_when_no_output():
    # unparseable plan → nothing runs → nothing to save
    runner = OrchestratorRunner(loop=None, provider=FakeProvider("よくわからない"))
    _ = [l async for l in runner.run("ゴール")]
    assert deliverables.list_deliverables() == []


async def test_orchestrate_captures_generated_files_as_artifacts():
    import json

    class FileLoop:
        async def run(self, goal, *, agent_name, system=None, max_iterations=6):
            yield LogLine("ok", "agent finished ✓")
            yield LogLine("out", "テキストレポート")
            yield LogLine("file", json.dumps({"path": "out.md", "size": 6, "content": "# 見出し"}))

    runner = OrchestratorRunner(loop=FileLoop(), provider=FakeProvider("Builder: A\nDONE"))
    out = await _collect_lines(runner, "ゴール")
    joined = "\n".join(out)
    assert "📄 生成ファイル: out.md" in joined       # friendly display, not raw JSON
    assert '{"path"' not in joined                    # raw file JSON is swallowed
    saved = deliverables.get(deliverables.list_deliverables()[0]["id"])
    tasks = {a["task"]: a["content"] for a in saved["artifacts"]}
    assert tasks["ファイル: out.md"] == "# 見出し"     # file captured as an artifact
    assert "テキストレポート" in "".join(saved_contents(saved))


def saved_contents(item):
    return [a["content"] for a in item["artifacts"]]


async def _collect_lines(runner, goal, **kw):
    return [l.s async for l in runner.run(goal, **kw)]


def test_artifacts_from_lines_parses_file_lines():
    import json
    lines = [
        {"t": "ok", "s": "agent finished ✓"},
        {"t": "out", "s": "本文レポート"},
        {"t": "file", "s": json.dumps({"path": "note.md", "size": 4, "content": "本文だよ"})},
    ]
    arts = deliverables.artifacts_from_lines(lines)
    tasks = {a["task"]: a["content"] for a in arts}
    assert tasks["ファイル: note.md"] == "本文だよ"
    assert any("本文レポート" in a["content"] for a in arts if not a["task"].startswith("ファイル"))


def test_sandbox_info_endpoint():
    info = client.get("/execution/sandbox-info").json()
    assert "runtime" in info and "persistent_sandbox" in info
    assert "collect_files" in info and "default_allow_domains" in info
