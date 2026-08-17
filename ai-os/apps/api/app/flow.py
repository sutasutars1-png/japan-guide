"""Multi-agent flow runner (roadmap Phase 4, design §フロー / ハンドオフ規約).

A Flow is an ordered list of stations (stages). The runner drives them:
each station runs its own PLAN→EXECUTE→OBSERVE agent loop, and its final DONE
report is handed to the next station as context. Routing is the station's
`next` by default; an agent may override it by ending its report with a
`→NEXT: <Stage>` (or `→NEXT: DONE`) line — the system-owned handoff protocol.
Bounded by `max_iterations` (total station runs).

Safety carries over from the inner loop: blocked commands never run, and a
high-risk (L3/L4) command halts — the flow stops rather than auto-destruct.
"""
from __future__ import annotations

import json
import re
from typing import AsyncIterator
from uuid import uuid4

from . import agents_store
from .agent_loop import AgentLoop, get_agent_loop
from .core.audit import AuditEvent, log
from .execution_manager import LogLine
from .json_store import load_json, save_json
from .skills import compose_system

_STORE_FILE = ".aios-flows.json"
_CUSTOM_PREFIX = "flow.custom."

SEED_FLOWS: list[dict] = [
    {"id": "flow.default", "name": "標準フロー", "max_iterations": 10,
     "stations": [
         {"agent": "Planner", "next": "Builder"},
         {"agent": "Builder", "next": "Reviewer"},
         {"agent": "Reviewer", "next": "DONE"},
     ]},
    {"id": "flow.solo", "name": "Builder単独", "max_iterations": 6,
     "stations": [{"agent": "Builder", "next": "DONE"}]},
    {"id": "flow.research", "name": "調査→分析", "max_iterations": 8,
     "stations": [
         {"agent": "Researcher", "next": "Builder"},
         {"agent": "Builder", "next": "DONE"},
     ]},
]


def _load_custom() -> list[dict]:
    data = load_json(_STORE_FILE, [])
    return [f for f in data if isinstance(f, dict) and f.get("id")] if isinstance(data, list) else []


# User-created flows are persisted (git-ignored `.aios-flows.json`) and survive a
# restart; the seed flows above are read-only defaults.
_custom: list[dict] = _load_custom()


def _save() -> None:
    save_json(_STORE_FILE, _custom)


def is_custom(flow_id: str) -> bool:
    return str(flow_id).startswith(_CUSTOM_PREFIX)


def _all() -> list[dict]:
    return SEED_FLOWS + _custom


def list_flows() -> list[dict]:
    return _all()


def get_flow(flow_id: str) -> dict | None:
    return next((f for f in _all() if f["id"] == flow_id), None)


def _clean_stations(stations: list[dict]) -> list[dict]:
    out = []
    for s in stations or []:
        agent = str((s or {}).get("agent", "")).strip()
        if agent:
            out.append({"agent": agent, "next": str(s.get("next", "DONE")).strip() or "DONE"})
    return out


def add_flow(name: str, stations: list[dict], max_iterations: int = 10) -> dict:
    flow = {
        "id": _CUSTOM_PREFIX + uuid4().hex[:8],
        "name": (name or "カスタムフロー").strip(),
        "max_iterations": max(1, int(max_iterations or 10)),
        "stations": _clean_stations(stations),
    }
    _custom.append(flow)
    _save()
    return flow


def update_flow(flow_id: str, changes: dict) -> dict | None:
    """Edit a CUSTOM flow. Seed flows are read-only (returns None)."""
    if not is_custom(flow_id):
        return None
    for f in _custom:
        if f["id"] == flow_id:
            if changes.get("name") is not None:
                f["name"] = str(changes["name"]).strip() or f["name"]
            if changes.get("max_iterations") is not None:
                f["max_iterations"] = max(1, int(changes["max_iterations"]))
            if changes.get("stations") is not None:
                f["stations"] = _clean_stations(changes["stations"])
            _save()
            return f
    return None


def remove_flow(flow_id: str) -> bool:
    """Delete a CUSTOM flow. Seed flows can't be deleted."""
    if not is_custom(flow_id):
        return False
    for i, f in enumerate(_custom):
        if f["id"] == flow_id:
            del _custom[i]
            _save()
            return True
    return False


def reset_to_seed() -> None:
    """Drop all custom flows (used by tests)."""
    global _custom
    _custom = []
    _save()


def flow_handoff_note(stage: str, stages: list[str]) -> str:
    others = "、".join(s for s in stages if s != stage) or "（なし）"
    return (
        "# フロー連携\n"
        f"あなたはパイプラインの工程『{stage}』です。あなたのDONE報告は次の工程に引き継がれます。"
        f"作業を別の工程へ戻すべきときは、DONE報告の最後に『→NEXT: <工程名>』の行を付けてください"
        f"（選べる工程: {others}）。ゴール全体が完了したら『→NEXT: DONE』と書いてください。"
        "指定がなければ既定の次工程へ進みます。"
    )


def parse_next(report: str, stages: list[str]) -> str | None:
    """Extract a `→NEXT: X` routing override from a report, or None."""
    for line in report.splitlines():
        m = re.match(r"^[\s→\-\>]*NEXT\s*[:：]\s*(\S+)", line.strip(), re.IGNORECASE)
        if m:
            val = m.group(1).strip().rstrip("。.")
            if val.upper() == "DONE":
                return "DONE"
            for st in stages:
                if st.lower() == val.lower():
                    return st
            return "DONE"
    return None


class FlowRunner:
    def __init__(self, loop: AgentLoop | None = None) -> None:
        self._loop = loop or get_agent_loop()

    async def run(
        self, goal: str, flow: dict, *, per_agent_iters: int = 6
    ) -> AsyncIterator[LogLine]:
        stations = flow["stations"]
        stage_names = [s["agent"] for s in stations]
        idx_by_stage = {s["agent"]: i for i, s in enumerate(stations)}
        max_it = flow.get("max_iterations", 10)

        yield LogLine("sys", f"フロー『{flow['name']}』開始 · ゴール: {goal}")
        log.append(AuditEvent("flow.start", "human", f"{flow['id']}: {goal}"))

        context = goal
        cur = 0
        runs = 0
        while runs < max_it:
            station = stations[cur]
            stage = station["agent"]
            yield LogLine("sys", f"▶ 工程 {runs + 1}: {stage}")

            system = compose_system(stage, agents_store.skills_for(stage)) or ""
            system = (system + "\n\n" + flow_handoff_note(stage, stage_names)).strip()

            report_lines: list[str] = []
            capturing = False
            halted = False
            async for line in self._loop.run(
                context, agent_name=stage, system=system, max_iterations=per_agent_iters
            ):
                if line.t == "file":  # generated file — note it, show a friendly line
                    try:
                        meta = json.loads(line.s)
                        note = f"生成ファイル: {meta['path']} ({meta.get('size', 0)}B)"
                    except Exception:  # noqa: BLE001
                        note = "生成ファイル"
                    report_lines.append(note)
                    yield LogLine("out", f"[{stage}] 📄 {note}")
                    continue
                if line.t == "ok" and line.s == "agent finished ✓":
                    capturing = True
                elif capturing and line.t == "out":
                    report_lines.append(line.s)
                if line.t == "halt":
                    halted = True
                yield LogLine(line.t, f"[{stage}] {line.s}")

            if halted:
                yield LogLine("halt", f"工程 {stage} が承認待ちで停止。フローを止めます。")
                return
            report = "\n".join(report_lines).strip()
            if not report:
                yield LogLine("warn", f"工程 {stage} が成果物なしで終了。フローを停止します。")
                return

            runs += 1
            nxt = parse_next(report, stage_names) or station.get("next", "DONE")
            if nxt == "DONE":
                yield LogLine("ok", "フロー完了 ✓")
                log.append(AuditEvent("flow.done", "human", flow["id"]))
                return
            cur = idx_by_stage.get(nxt)
            if cur is None:
                yield LogLine("ok", "フロー完了 ✓（次工程が未定義）")
                return
            context = f"前工程（{stage}）の成果物:\n{report}\n\n元のゴール: {goal}"

        yield LogLine("warn", f"最大反復（{max_it}）に達したためフローを停止しました。")
        log.append(AuditEvent("flow.max", "human", flow["id"]))


_runner: FlowRunner | None = None


def get_flow_runner() -> FlowRunner:
    global _runner
    if _runner is None:
        _runner = FlowRunner()
    return _runner
