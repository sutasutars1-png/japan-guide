"""AI組織自身の自己改善 — Skill 改善ループ (§20)。

    現行Skill → 改善案 → テスト → 旧版比較 → 改善効果確認 → 承認 → 新Skillとして採用

**直接上書きは禁止**（§20）。改善は必ず新しい version として積み、変更履歴と
評価を残す（§44-12）。採用は Human Approval（kind=`config`, §21）を通す。

実体は `data/skills/<key>.json`:
    {key, current, versions: [ {version, purpose, success, forbidden, guidance,
                                author, created_at, status, eval} ]}
status: seed | candidate | adopted | retired
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from . import ids
from .approval import ApprovalGateway
from .memory import CompanyMemory
from .models import Decision
from .skills import SKILLS
from .storage import Storage

# 改善効果を測る評価器の型: (candidate, current|None) -> (score: float, detail: dict)
Evaluator = Callable[[dict, Optional[dict]], "tuple[float, dict]"]


def heuristic_eval(candidate: dict, current: dict | None) -> "tuple[float, dict]":
    """外部依存なしの既定評価器（完成度ヒューリスティック）。

    本物の効果測定は「同じ入力で新旧 Skill の出力品質を比べる」ことだが、初期は
    定義そのものの充実度を代理指標にする。LLM 評価器を差し込めば実出力比較も可能。
    """
    detail: dict[str, Any] = {}
    score = 0.0
    if candidate.get("purpose"):
        score += 1
    if candidate.get("success"):
        score += 1
    if candidate.get("guidance"):
        score += 2  # 具体的な手順があると加点
    forb = candidate.get("forbidden") or []
    score += min(len(forb), 3) * 0.5
    detail["candidate_score"] = score
    if current is not None:
        base = 0.0
        base += 1 if current.get("purpose") else 0
        base += 1 if current.get("success") else 0
        base += 2 if current.get("guidance") else 0
        base += min(len(current.get("forbidden") or []), 3) * 0.5
        detail["current_score"] = base
        detail["delta"] = round(score - base, 2)
        detail["improved"] = score > base
    else:
        detail["improved"] = True
    return score, detail


class SkillLab:
    def __init__(self, storage: Storage, approvals: ApprovalGateway,
                 memory: CompanyMemory | None = None):
        self.storage = storage
        self.approvals = approvals
        self.memory = memory

    # ---- seed / 取得 ------------------------------------------------------

    def _seed(self, key: str) -> dict[str, Any]:
        spec = SKILLS[key]
        rec = {
            "id": key, "key": key, "current": 1,
            "versions": [{
                "version": 1, "purpose": spec.purpose, "success": spec.success,
                "forbidden": list(spec.forbidden), "guidance": "",
                "author": "seed", "created_at": ids.now_iso(),
                "status": "adopted", "eval": {},
            }],
        }
        self.storage.put("skills", rec)
        return rec

    def record(self, key: str) -> dict[str, Any]:
        if key not in SKILLS:
            raise KeyError(f"未知の Skill: {key}")
        rec = self.storage.get("skills", key)
        return rec or self._seed(key)

    def _version(self, rec: dict, version: int) -> dict | None:
        return next((v for v in rec["versions"] if v["version"] == version), None)

    def current(self, key: str) -> dict[str, Any]:
        rec = self.record(key)
        return self._version(rec, rec["current"])  # type: ignore[return-value]

    def text(self, key: str) -> str:
        """ClaudeRunner に渡す現行版のガイダンステキスト。"""
        try:
            v = self.current(key)
        except KeyError:
            return ""
        forb = "、".join(v.get("forbidden") or []) or "（特になし）"
        guide = f" / 手順: {v['guidance']}" if v.get("guidance") else ""
        return (f"[Skill: {key} v{v['version']}] 目的: {v['purpose']} / "
                f"成功条件: {v['success']} / 禁止事項: {forb}{guide}")

    # ---- 改善案 (§20) -----------------------------------------------------

    def propose(self, key: str, *, purpose: str | None = None,
                success: str | None = None, forbidden: list[str] | None = None,
                guidance: str | None = None, author: str = "growth") -> dict[str, Any]:
        """現行版をベースに改善案を**新 version として**積む（上書きしない）。"""
        rec = self.record(key)
        base = self._version(rec, rec["current"]) or {}
        new_version = max(v["version"] for v in rec["versions"]) + 1
        candidate = {
            "version": new_version,
            "purpose": purpose if purpose is not None else base.get("purpose", ""),
            "success": success if success is not None else base.get("success", ""),
            "forbidden": forbidden if forbidden is not None else list(base.get("forbidden", [])),
            "guidance": guidance if guidance is not None else base.get("guidance", ""),
            "author": author, "created_at": ids.now_iso(),
            "status": "candidate", "eval": {},
        }
        rec["versions"].append(candidate)
        self.storage.put("skills", rec)
        if self.memory:
            self.memory.add("improvement", f"Skill改善案 {key} v{new_version}",
                            candidate.get("guidance", ""), tags=[key])
        return candidate

    # ---- テスト / 旧版比較 (§20) -----------------------------------------

    def evaluate(self, key: str, version: int,
                 evaluator: Evaluator = heuristic_eval) -> dict[str, Any]:
        rec = self.record(key)
        cand = self._version(rec, version)
        if cand is None:
            raise KeyError(f"{key} v{version} が無い")
        current = self._version(rec, rec["current"])
        score, detail = evaluator(cand, current if current is not version else None)
        cand["eval"] = {"score": score, **detail}
        self.storage.put("skills", rec)
        return cand["eval"]

    # ---- 承認 → 採用 (§20, §21) ------------------------------------------

    def request_adoption(self, key: str, version: int) -> dict[str, Any]:
        rec = self.record(key)
        cand = self._version(rec, version)
        if cand is None:
            raise KeyError(f"{key} v{version} が無い")
        if not cand.get("eval"):
            self.evaluate(key, version)
            cand = self._version(rec, version)
        apr = self.approvals.request(
            "config", f"Skill採用の承認: {key} v{version}",
            {"skill": key, "version": version, "eval": cand.get("eval", {})},
            requested_by="growth",
        )
        return apr.to_dict()

    def adopt(self, key: str, version: int, approval_id: str) -> dict[str, Any]:
        """承認済みなら current を差し替える。旧版は retired にして履歴を残す。"""
        self.approvals.guard("config", approval_id)  # 未承認なら例外
        rec = self.record(key)
        cand = self._version(rec, version)
        if cand is None:
            raise KeyError(f"{key} v{version} が無い")
        prev = rec["current"]
        for v in rec["versions"]:
            if v["version"] == prev and v["status"] == "adopted":
                v["status"] = "retired"
        cand["status"] = "adopted"
        rec["current"] = version
        self.storage.put("skills", rec)

        # 変更履歴（§44-11, §44-12）
        dec = Decision(
            actor="growth", context=f"Skill採用 {key}",
            decision=f"{key} を v{prev} → v{version} に更新",
            rationale=f"評価 {cand.get('eval', {})}（§20 改善効果確認・承認済み）",
            related=[key],
        )
        self.storage.append("decisions", dec.to_dict())
        if self.memory:
            self.memory.add("improvement", f"Skill採用 {key} v{version}",
                            f"v{prev}→v{version}", tags=[key])
        return cand

    # ---- 参照 -------------------------------------------------------------

    def versions(self, key: str) -> list[dict[str, Any]]:
        return self.record(key)["versions"]

    def all_current(self) -> list[dict[str, Any]]:
        out = []
        for key in SKILLS:
            v = self.current(key)
            out.append({"key": key, "version": v["version"], "purpose": v["purpose"],
                        "candidates": sum(1 for x in self.versions(key)
                                          if x["status"] == "candidate")})
        return out
