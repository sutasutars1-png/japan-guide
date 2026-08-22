"""ClaudeRunner — Claude Code CLI を使う実 LLM ランナー（§42 の差し込み実装）。

`ai-os` で実証済みの「キーレス・サブスクリプション」方式を踏襲する:

- ユーザー自身のログイン済み `claude` バイナリに `-p`（ヘッドレス）で問い合わせる。
  API キーは使わないので **従量課金は発生しない**（§36 Pro 範囲）。
- API 課金に切り替わる環境変数（``ANTHROPIC_API_KEY`` など）はサブプロセスの
  env から除去し、必ずサブスクリプション・ログインを使わせる。
- `--dangerously-skip-permissions` は渡さない。ツールは全て禁止（テキスト生成のみ）。
- 生成は「頭脳」チャネル（ホスト側）で、ファイル実行の「手」とは分離する。

各 Agent の役割（§4）と Skill の 8 項目（§19）からプロンプトを組み立て、
**厳密な JSON** で返させて `TemplateRunner` と同じ出力形に整える。失敗時
（バイナリ無し / タイムアウト / JSON 不正）は `TemplateRunner` へ**フォールバック**
し、`_llm_error` を付けて正直に劣化させる。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any, Callable

from . import agents as agents_mod
from . import skills as skills_mod
from .runner import TemplateRunner

# API 課金に切り替わる env（サブプロセスから除去）。
_API_BILLING_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")

# task_type → (担当Agent, 使用Skill)。プロンプトの役割・技能の源。
TASK_ROLE: dict[str, tuple[str, str]] = {
    "research": ("researcher", "market-research"),
    "product_plan": ("cpo", "product-planning"),
    "article_write": ("writer", "article-writing"),
    "review_final": ("reviewer", "quality-review"),
    "x_post": ("marketing", "x-marketing"),
    "tiktok_script": ("marketing", "tiktok-marketing"),
}

# task_type → 期待する JSON キー（検証用）と追加指示。
_CONTRACT: dict[str, dict[str, Any]] = {
    "research": {
        "keys": ["theme", "demand_signals", "note"],
        "instruction": (
            "テーマの需要を『何が売れそうか』の観点で分析し、"
            "demand_signals には検証可能な需要仮説を3〜5件（配列）入れる。"
            "断定を避け、各仮説は簡潔な日本語1文。"
        ),
    },
    "product_plan": {
        "keys": [
            "product_name", "target", "reader_pain", "purchase_reason",
            "problem_solved", "free_part", "paid_part", "price_jpy",
            "competitors", "differentiation", "why_sells",
            "success_probability", "risk", "experiment_purpose",
        ],
        "instruction": (
            "§13 の商品企画フォーマットを全項目埋める。price_jpy は入力の価格を使う。"
            "success_probability は『低』『中』『高』のいずれか。"
            "景表法（優良誤認）に触れる断定（『必ず稼げる』等）は禁止。"
            "入力 avoid_similar は既存商品の一覧。これらと product_name・切り口・"
            "reader_pain が重複しないよう、別の読者層/悩み/角度で差別化する。"
            "入力 performance_hints があれば winning_angles の切り口に寄せ、"
            "losing_angles は避ける（実績に基づく学習, §31）。"
        ),
    },
    "article_write": {
        "keys": ["title", "outline", "body_markdown", "cta"],
        "instruction": (
            "note 記事を書く。outline は配列。body_markdown は Markdown 本文で、"
            "無料部分→『―― ここから有料 ――』→有料部分→まとめ の構成。"
            "読者価値を中心に、誇張・誤情報を避ける。プレースホルダ（[ ]）は残さない。"
            "入力 avoid_similar は既存記事の一覧。見出し構成・具体例・言い回しが"
            "これらと似ないよう、独自の切り口と事例で書く。"
            "入力 price_requirement の分量・具体例・チェックリスト等の要件を必ず満たす"
            "（価格に見合う密度）。performance_hints があれば winning_angles に寄せる。"
            "入力に feedback がある場合は、その差し戻し指摘を必ず反映して "
            "previous_body を改稿する（具体例・手順・固有名詞を補い、断定表現を是正）。"
        ),
    },
    "x_post": {
        "keys": ["channel", "posts", "hashtags", "note"],
        "instruction": (
            "無料記事から note の有料記事へ誘導する X 投稿案を作る（§32）。"
            "posts は3〜4件の短文（各140字以内）の配列で、最後に note への誘導を含める。"
            "channel は 'x'。誇張・断定（景表法優良誤認）を避ける。自動投稿はしない前提の下書き。"
        ),
    },
    "tiktok_script": {
        "keys": ["channel", "hook", "script", "captions", "hashtags", "note"],
        "instruction": (
            "売れた記事をショート動画化する台本を作る（§33）。channel は 'tiktok'。"
            "hook は最初の3秒の一言、script は秒数付きの構成配列、captions は字幕案の配列。"
            "note への導線を含める。誇張・断定を避ける。撮影・投稿は人間が行う前提の下書き。"
        ),
    },
    "review_final": {
        "keys": ["verdict", "checklist", "notes"],
        "instruction": (
            "§4 の観点 + 法的チェック（特商法・景表法・著作権）で記事を点検する。"
            "verdict は 'pass' か 'reject'。checklist は各観点→短評の辞書。"
            "重大な問題や未完なら reject にし、notes に差し戻し理由を書く。"
        ),
    },
}


class ClaudeRunner:
    def __init__(
        self,
        *,
        claude_bin: str = "claude",
        model: str | None = None,
        timeout_s: int = 300,
        force_subscription: bool = True,
        fallback: TemplateRunner | None = None,
        skill_text: Callable[[str], str] | None = None,
    ):
        self.claude_bin = claude_bin
        self.model = model
        self.timeout_s = timeout_s
        self.force_subscription = force_subscription
        self.fallback = fallback or TemplateRunner()
        # Skill の現行版テキストを差し込むフック（自己改善版を反映できる）。
        self.skill_text = skill_text

    # ---- 可用性 -----------------------------------------------------------

    @staticmethod
    def available(claude_bin: str = "claude") -> str | None:
        return shutil.which(claude_bin)

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        if self.force_subscription:
            for k in _API_BILLING_ENV:
                env.pop(k, None)
        return env

    def _argv(self, resolved: str) -> list[str]:
        argv = [resolved, "-p", "--output-format", "text",
                "--disallowed-tools", "Bash,Edit,Write,NotebookEdit,WebFetch,WebSearch,TodoWrite"]
        if self.model:
            argv += ["--model", self.model]
        return argv

    # ---- プロンプト組み立て ----------------------------------------------

    def _skill_block(self, skill_key: str) -> str:
        if self.skill_text is not None:
            return self.skill_text(skill_key)
        s = skills_mod.SKILLS.get(skill_key)
        if not s:
            return ""
        forbidden = "、".join(s.forbidden) or "（特になし）"
        return (f"[Skill: {skill_key}] 目的: {s.purpose} / 成功条件: {s.success} / "
                f"禁止事項: {forbidden}")

    def _build_prompt(self, task_type: str, payload: dict[str, Any]) -> str:
        agent_key, skill_key = TASK_ROLE.get(task_type, ("cpo", "product-planning"))
        agent = agents_mod.AGENTS.get(agent_key)
        contract = _CONTRACT.get(task_type, {"keys": [], "instruction": ""})
        role = f"あなたは {agent.name}。役割: {agent.role}" if agent else "あなたは担当AI。"
        skill = self._skill_block(skill_key)
        keys = contract["keys"]
        # payload から巨大になりうるものは要約せずそのまま渡す（初期はシンプルに）。
        ctx = {k: v for k, v in payload.items() if k != "task_type"}
        keyspec = ", ".join(f'"{k}"' for k in keys)
        return (
            f"{role}\n{skill}\n\n"
            f"# 指示\n{contract['instruction']}\n\n"
            f"# 入力(JSON)\n{json.dumps(ctx, ensure_ascii=False)}\n\n"
            f"# 出力形式\n"
            f"次のキーだけを持つ JSON オブジェクトを1つ**だけ**出力する: {keyspec}。\n"
            f"前置き・説明・コードフェンス(```)は一切書かない。JSON のみ。"
        )

    # ---- 実行 -------------------------------------------------------------

    def run(self, task_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        resolved = shutil.which(self.claude_bin)
        if task_type not in _CONTRACT or resolved is None:
            out = self.fallback.run(task_type, payload)
            out["_llm_error"] = (
                "claude CLI 未検出" if resolved is None else f"未対応task '{task_type}'"
            )
            return out

        prompt = self._build_prompt(task_type, payload)
        try:
            proc = subprocess.run(
                self._argv(resolved), input=prompt.encode("utf-8"),
                capture_output=True, timeout=self.timeout_s, env=self._env(),
            )
        except subprocess.TimeoutExpired:
            return self._fallback(task_type, payload, "claude CLI タイムアウト")
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or b"").decode("utf-8", "replace").strip()
            return self._fallback(task_type, payload, f"claude CLI エラー: {detail[:200]}")

        text = (proc.stdout or b"").decode("utf-8", "replace").strip()
        parsed = _extract_json(text)
        if parsed is None:
            return self._fallback(task_type, payload, "JSON 解析失敗")
        return self._coerce(task_type, parsed)

    def _fallback(self, task_type: str, payload: dict[str, Any], reason: str) -> dict[str, Any]:
        out = self.fallback.run(task_type, payload)
        out["_llm_error"] = reason
        return out

    def _coerce(self, task_type: str, parsed: dict[str, Any]) -> dict[str, Any]:
        """LLM 出力を各 task_type の期待形に軽く整える。"""
        if task_type == "review_final":
            v = str(parsed.get("verdict", "")).lower()
            parsed["verdict"] = "pass" if v.startswith("pass") else "reject"
            parsed.setdefault("checklist", {})
            parsed.setdefault("notes", "")
        elif task_type == "article_write":
            # LLM 記事は完成品なので is_skeleton は付けない（Reviewer を通過しうる）。
            parsed.setdefault("outline", [])
            parsed.setdefault("cta", "")
            parsed.setdefault("body_markdown", "")
        parsed["_llm"] = True
        return parsed


def _extract_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    # コードフェンス除去
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                text = part
                break
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    # strict=False: LLM は body_markdown 等に生の改行を入れがち。制御文字を許容する。
    try:
        obj = json.loads(text[start:end + 1], strict=False)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None
