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
    "system_improve": ("growth", "growth-strategy"),
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
            "入力 lessons は過去の差し戻しから学んだ必須の改善点。すべて必ず守る。"
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
            "入力 lessons は過去の差し戻しから学んだ必須の改善点。**すべて必ず守る**"
            "（特に具体例は数値・固有名詞・手順つきで十分な数を入れる）。"
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
    "system_improve": {
        "keys": ["proposals"],
        "instruction": (
            "あなたは Growth 責任者。入力 summary（KPI/成功失敗パターン/教訓）を読み、"
            "**売上を上げるためのシステム改修案**（機能追加・仕組み変更）を 3〜5 件提案する。"
            "proposals は配列で、各要素は "
            '{"title","problem","hypothesis","expected_effect","category","effort"} '
            "を持つ。category は funnel/pricing/channel/measurement/ux/quality/retention "
            "のいずれか、effort は S/M/L。コンテンツの小手先ではなく、仕組みの改善に絞る。"
            "コードの自動改変は求めていない（人間が実装可否を判断する提案）。"
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

    def preflight(self, timeout_s: int = 20) -> dict[str, Any]:
        """実 LLM の疎通確認（バイナリ有無 + ログイン状態）。

        `available()` はバイナリの存在しか見ないため、未ログインでも True になり
        「実LLM ON なのに毎回フォールバック」になりがち。ここは `claude auth status
        --json` で高速・無課金・確定的に判定する（生成本体はしない）。生成と同じく
        API 課金 env を除いた環境で確認し、サブスク（firstParty）状態を反映する。
        """
        resolved = shutil.which(self.claude_bin)
        if resolved is None:
            return {"ok": False, "reason": "no_binary",
                    "detail": "claude CLI が見つかりません（未インストール or PATH 未設定）"}
        try:
            proc = subprocess.run(
                [resolved, "auth", "status", "--json"],
                capture_output=True, timeout=timeout_s, env=self._env())
        except (subprocess.TimeoutExpired, OSError) as exc:
            return {"ok": False, "reason": "timeout",
                    "detail": f"応答なし/起動失敗: {str(exc)[:120]}"}
        text = (proc.stdout or b"").decode("utf-8", "replace").strip()
        data = _extract_json(text) or {}
        if data.get("loggedIn") is True:
            return {"ok": True, "reason": "ok",
                    "detail": f"ログイン済み（{data.get('authMethod', '')}/"
                              f"{data.get('apiProvider', '')}）".replace("（/）", "")}
        detail = (proc.stderr or b"").decode("utf-8", "replace").strip() or text
        low = (detail + " " + text).lower()
        if data.get("loggedIn") is False or any(
                k in low for k in ("logged in", "log in", "/login", "unauthorized")):
            return {"ok": False, "reason": "not_logged_in", "detail": "claude CLI が未ログインです"}
        return {"ok": False, "reason": "error", "detail": (detail or "auth status 解析失敗")[:200]}

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
        common = (
            f"{role}\n{skill}\n\n"
            f"# 指示\n{contract['instruction']}\n\n"
            f"# 入力(JSON)\n{json.dumps(ctx, ensure_ascii=False)}\n\n"
        )
        if task_type == "article_write":
            # 本文を JSON に埋め込むと壊れやすいので、メタ情報のみ JSON、本文は
            # 区切りの後に生 Markdown で出させる（頑健）。
            return common + (
                "# 出力形式（厳守）\n"
                '1行目に メタ情報のみの JSON を出力: {"title": "…", '
                '"outline": ["見出し1", "見出し2", …], "cta": "…"}。\n'
                f"次の行に、区切り記号だけの行: {_ARTICLE_BODY_MARK}\n"
                "その後に、記事本文を Markdown でそのまま書く（長さ自由・"
                "エスケープ不要・本文全体をコードフェンスで囲まない）。\n"
                "本文には JSON を書かない。区切りより前に本文を書かない。"
            )
        keyspec = ", ".join(f'"{k}"' for k in keys)
        return common + (
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
        parsed = _parse_article(text) if task_type == "article_write" \
            else _extract_json(text)
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


# 記事本文の区切り（JSON に長文を埋め込むと壊れやすいため本文だけ外に出す）。
_ARTICLE_BODY_MARK = "===本文ここから==="


def _strip_outer_fence(text: str) -> str:
    """全体が ```〜``` で囲まれている場合だけ外側フェンスを外す。"""
    t = text.strip()
    if t.startswith("```"):
        nl = t.find("\n")
        if nl != -1:
            t = t[nl + 1:]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


def _first_heading(body: str) -> str:
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("#"):
            return s.lstrip("#").strip()
    return ""


def _parse_article(text: str) -> dict[str, Any] | None:
    """article_write 出力を解析。メタJSON + 区切り + 生Markdown本文。

    本文を JSON 文字列に埋め込むと『"』『\\』『```』で壊れて解析失敗するため、
    本文は区切り記号の後にそのまま出させる（頑健）。区切りが無い場合は従来の
    JSON 抽出にフォールバックする。
    """
    if not text:
        return None
    if _ARTICLE_BODY_MARK in text:
        head, body = text.split(_ARTICLE_BODY_MARK, 1)
        meta = _extract_json(head) or {}
        body = _strip_outer_fence(body)
        if not body.strip():
            return None
        return {
            "title": meta.get("title") or _first_heading(body),
            "outline": meta.get("outline", []),
            "cta": meta.get("cta", ""),
            "body_markdown": body,
        }
    return _extract_json(text)


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
