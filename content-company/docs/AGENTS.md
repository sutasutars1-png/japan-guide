# AGENTS — AI会社の組織 (§4, §28, §35)

AI を「社員」として扱う（§3.1）。各 Agent は 役割 / 責任 / Skill / 判断基準 /
入力 / 出力 / 禁止事項 / 成功条件 を持つ。機械可読な定義は
`company/agents.py`、詳細な定義書は `agents/<key>.md`。

## 一覧

| key | 名称 | 既定Tier | 単独公開 | 主なSkill |
|---|---|---|---|---|
| `ceo` | CEO / 経営AI | 3 | — | growth-strategy |
| `researcher` | Researcher / リサーチAI | 2 | — | market-research, competitor-analysis, note-analysis, seo |
| `cpo` | CPO / 商品企画AI | 3 | — | product-planning |
| `writer` | Writer / 編集AI | 2 | **不可** | article-writing, seo |
| `reviewer` | Reviewer / 品質管理AI | 3 | — | quality-review |
| `marketing` | Marketing AI | 2 | — | x-marketing, tiktok-marketing |
| `analyst` | Data Analyst / 分析AI | 2 | — | data-analysis, sales-analysis |
| `growth` | Growth AI / 改善AI | 3 | — | growth-strategy |

> **Writer は単独で公開してはいけない。必ず Reviewer を通す**（§4）。コードでも
> `AgentSpec.can_publish=False` とし、公開は `ApprovalGateway` 経由に限定。

## MVP 構成（§28）

最初は 5 Agent（`MVP_AGENTS`）: **CEO / Researcher / CPO(Product Manager) /
Writer / Reviewer**。Marketing / Analytics / Growth は初期は CEO・Researcher・
CPO が兼務してよい。定義自体は最初から持つ（将来の分離に備える）。

## 最終形（§35）

```
        CEO
   ┌─────┼─────┐
Research Product Analytics
         │
       Writer → Reviewer → (承認) → note → Sales → Analytics → Growth → CEO
         Marketing → X / TikTok → note
```

## 判断基準（CEO, §4）

売上につながるか / 再現性があるか / 自動化できるか / コストに見合うか /
リスクは許容範囲か。CEO の判断は `Decision` として根拠付きで保存する（§44-11）。
