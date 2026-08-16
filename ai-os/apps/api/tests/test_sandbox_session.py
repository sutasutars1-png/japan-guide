"""Persistent-sandbox session, materials copy-in, file collection, and the
agent-loop integration — all on the local runtime, no Docker/network."""
import json
import os

os.environ.setdefault("AIOS_ALLOW_UNSAFE_LOCAL", "1")

import pytest  # noqa: E402

from app import materials  # noqa: E402
from app.agent_loop import AgentLoop, _resolve_domains  # noqa: E402
from app.core.llm.base import LLMResponse, LLMUsage  # noqa: E402
from app.core.sandbox.local_runtime import LocalSubprocessRuntime  # noqa: E402
from app.execution_manager import ExecutionManager  # noqa: E402


class SeqProvider:
    """Yields successive replies (one per turn)."""
    name = "fake"

    def __init__(self, replies):
        self._replies = list(replies)
        self._i = 0

    async def complete(self, messages, *, model, tools=None, max_tokens=1024):
        text = self._replies[min(self._i, len(self._replies) - 1)]
        self._i += 1
        return LLMResponse(text=text, usage=LLMUsage(input_tokens=1, output_tokens=1))


def _mgr():
    return ExecutionManager(LocalSubprocessRuntime())


# ---- materials copy-in filtering --------------------------------------------

def test_iter_materials_filters_secrets_and_binaries(tmp_path):
    (tmp_path / "readme.md").write_text("# hi", encoding="utf-8")
    (tmp_path / "app.py").write_text("print(1)", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=xyz", encoding="utf-8")          # denied
    (tmp_path / "id.pem").write_text("KEY", encoding="utf-8")               # denied
    (tmp_path / "pic.png").write_bytes(b"\x89PNG\x00\x00")                  # binary/ext
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("x", encoding="utf-8")        # denied dir
    got = {rel for rel, _ in materials.iter_materials(
        str(tmp_path), max_files=50, max_bytes=1_000_000, per_file_bytes=1_000_000)}
    assert got == {"readme.md", "app.py"}


def test_iter_materials_respects_caps(tmp_path):
    for i in range(10):
        (tmp_path / f"f{i}.txt").write_text("data", encoding="utf-8")
    got = materials.iter_materials(str(tmp_path), max_files=3, max_bytes=1_000_000, per_file_bytes=1_000_000)
    assert len(got) == 3


# ---- session: files persist across commands + get collected -----------------

async def test_session_persists_files_and_collects_them():
    mgr = _mgr()
    handle, prep = await mgr.open_session(actor="Builder", allow_domains=[], materials=False)
    try:
        assert any("created" in l.s for l in prep)
        # two separate commands in the SAME sandbox — the file must survive
        _ = [l async for l in mgr.exec_in(handle, "printf 'part1\\n' > out.txt", actor="Builder")]
        _ = [l async for l in mgr.exec_in(handle, "printf 'part2\\n' >> out.txt", actor="Builder")]
        files = await mgr.collect_files(handle)
    finally:
        await mgr.close_session(handle)
    by_path = {f["path"]: f for f in files}
    assert "out.txt" in by_path
    assert "part1" in by_path["out.txt"]["content"] and "part2" in by_path["out.txt"]["content"]


async def test_collect_excludes_materials_dir(tmp_path, monkeypatch):
    # point the live settings at a materials dir (no module reload needed —
    # execution_manager reads settings.* at call time)
    monkeypatch.setattr("app.execution_manager.settings.workspace_mount", str(tmp_path))
    (tmp_path / "source.md").write_text("original", encoding="utf-8")
    mgr = _mgr()
    handle, prep = await mgr.open_session(actor="Builder", materials=True)
    try:
        assert any("資料" in l.s for l in prep)          # materials copied in
        _ = [l async for l in mgr.exec_in(handle, "printf 'new' > deliverable.txt", actor="Builder")]
        files = await mgr.collect_files(handle)
    finally:
        await mgr.close_session(handle)
    paths = {f["path"] for f in files}
    assert "deliverable.txt" in paths
    assert not any(p.startswith("materials/") for p in paths)  # source material not re-collected


# ---- agent loop emits file lines --------------------------------------------

async def test_agent_loop_emits_generated_file():
    loop = AgentLoop(
        provider=SeqProvider(["RUN: printf 'result body' > result.txt", "DONE: 完了しました"]),
        manager=_mgr(), model="fake",
    )
    lines = [l async for l in loop.run("目標", agent_name="Builder", max_iterations=4)]
    file_lines = [l for l in lines if l.t == "file"]
    assert file_lines, "expected a file line for the generated file"
    meta = json.loads(file_lines[0].s)
    assert meta["path"] == "result.txt" and "result body" in meta["content"]
    assert any(l.t == "ok" and l.s == "agent finished ✓" for l in lines)


# ---- allowlist resolution ---------------------------------------------------

def test_resolve_domains_merges_and_dedupes(monkeypatch):
    monkeypatch.setattr("app.agent_loop.settings.default_allow_domains", ["pypi.org"])
    # explicit ∪ default, de-duped, order preserved
    out = _resolve_domains("NoSuchAgent", ["note.com", "pypi.org", ""])
    assert out == ["note.com", "pypi.org"]
