"""agents/ と skills/ の定義書を registry から生成する。

registry（company/agents.py, company/skills.py）を単一の真実とし、人間向けの
Markdown 定義書をそこから起こす。手編集した本文は ``<!-- CUSTOM -->`` 以降に
書けば再生成で保持される。

    python3 tools/gen_defs.py
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from company.agents import AGENTS  # noqa: E402
from company.skills import SKILLS  # noqa: E402

CUSTOM_MARK = "<!-- CUSTOM: この行より下は手編集可。再生成で保持されます。 -->"


def _keep_custom(path: pathlib.Path) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    if CUSTOM_MARK in text:
        return text.split(CUSTOM_MARK, 1)[1]
    return ""


def gen_agent(key: str) -> None:
    a = AGENTS[key]
    skills = "\n".join(f"- `{s}`" for s in a.skills) or "- （なし）"
    path = ROOT / "agents" / f"{key}.md"
    custom = _keep_custom(path)
    custom_block = custom or "\n"
    body = f"""# Agent: {a.name}

> 自動生成（`tools/gen_defs.py`）。定義の源は `company/agents.py`。

- **key**: `{a.key}`
- **既定モデル Tier**: {a.default_tier}（§14）
- **単独公開**: {"可" if a.can_publish else "不可（必ず Reviewer / 承認を通す, §4）"}

## 役割・責任
{a.role}

## 使用 Skill（§19）
{skills}

## 8項目（§3.1 — 詳細は下の CUSTOM 節に追記）
- 役割 / 責任: 上記
- 判断基準: 売上・再現性・自動化可否・コスト・リスク（§4）
- 入力: 担当 Task の `input`
- 出力: Task の `output`（後段 Agent が利用）
- 禁止事項: 未検証情報の断定、承認なしの外部操作（§21）
- 成功条件: 担当 Skill の成功条件を満たすこと

{CUSTOM_MARK}{custom_block}"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def gen_skill(key: str) -> None:
    s = SKILLS[key]
    forbidden = "\n".join(f"- {x}" for x in s.forbidden) or "- （特になし）"
    path = ROOT / "skills" / key / "SKILL.md"
    custom = _keep_custom(path)
    custom_block = custom or "\n"
    body = f"""# Skill: {key}

> 自動生成（`tools/gen_defs.py`）。定義の源は `company/skills.py`。version {s.version}。

## 目的
{s.purpose}

## 成功条件
{s.success}

## 禁止事項
{forbidden}

## 手順 / 判断基準 / 入力 / 出力
- 手順: （CUSTOM 節に具体手順を記述）
- 判断基準: 成功条件を満たすか
- 入力: 担当 Task の `input`
- 出力: 担当 Task の `output`

## 自己改善（§20）
直接上書き禁止。改善案→テスト→旧版比較→効果確認→承認→**新 version として採用**。

{CUSTOM_MARK}{custom_block}"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def main() -> None:
    for key in AGENTS:
        gen_agent(key)
    for key in SKILLS:
        gen_skill(key)
    print(f"generated {len(AGENTS)} agents, {len(SKILLS)} skills")


if __name__ == "__main__":
    main()
