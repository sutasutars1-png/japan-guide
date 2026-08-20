"""ダッシュボード生成 (§25)。

data/ の内容から静的 HTML を1枚出力する。外部 CSS/JS に依存しない。
経営KPI / 商品ランキング / AI組織(タスク) / 実験 / コスト を表示する。
"""

from __future__ import annotations

import html
from typing import Any

from .company import Company


def _esc(x: Any) -> str:
    return html.escape(str(x))


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    head = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{_esc(c)}</td>" for c in r) + "</tr>" for r in rows
    )
    if not rows:
        body = f'<tr><td colspan="{len(headers)}" class="muted">データなし</td></tr>'
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _cards(items: list[tuple[str, Any]]) -> str:
    return "".join(
        f'<div class="card"><div class="k">{_esc(k)}</div>'
        f'<div class="v">{_esc(v)}</div></div>'
        for k, v in items
    )


def render(company: Company) -> str:
    s = company.kpi.summary()
    tasks = company.storage.all("tasks")
    task_counts: dict[str, int] = {}
    for t in tasks:
        task_counts[t.get("status", "?")] = task_counts.get(t.get("status", "?"), 0) + 1
    pending = company.approvals.pending()
    exp = company.experiments.progress()
    cost_by_tier = company.cost.units_by_tier()
    cost_by_agent = company.cost.units_by_agent()

    kpi_cards = _cards([
        ("総売上 (円)", f"{s['total_revenue_jpy']:,}"),
        ("今月売上 (円)", f"{s['month_revenue_jpy']:,}"),
        ("商品数", s["product_count"]),
        ("公開数", s["published_count"]),
        ("購入数", s["purchases"]),
        ("PV", f"{s['pv']:,}"),
        ("購入率", f"{s['conversion_rate']:.2%}"),
        ("AIコスト(units)", s.get("ai_cost_units", 0)),
        ("1商品あたりAIコスト", s.get("ai_cost_per_product", 0)),
    ])

    ranking_rows = [
        [p.get("title"), p.get("category"), f"{int(p.get('revenue_jpy', 0)):,}",
         p.get("pv"), f"{float(p.get('conversion_rate', 0)):.1%}", p.get("outcome") or "-"]
        for p in company.kpi.ranking("revenue_jpy", 10)
    ]
    task_rows = [[k, v] for k, v in sorted(task_counts.items())]
    pending_rows = [[a.get("kind"), a.get("summary"), a.get("id")] for a in pending]
    cat_rows = [[c, n, "撤退" if c in exp["retreated"] else "継続"]
                for c, n in exp["category_ranking"]]  # type: ignore[index]
    tier_rows = [[f"Tier {t}", round(u, 1)] for t, u in sorted(cost_by_tier.items())]
    agent_rows = [[a, round(u, 1)] for a, u in sorted(cost_by_agent.items())]

    target_badge = "✅ 達成" if s["conversion_target_met"] else "未達"

    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AIコンテンツ販売会社 ダッシュボード</title>
<style>
:root{{color-scheme:light dark}}
*{{box-sizing:border-box}}
body{{font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;margin:0;
background:#0b0e14;color:#e6e9ef;line-height:1.5}}
header{{padding:24px 28px;border-bottom:1px solid #232838;background:#111624}}
h1{{margin:0;font-size:20px}} h2{{font-size:15px;margin:28px 0 10px;color:#9fb4d8}}
.sub{{color:#7c89a3;font-size:13px;margin-top:4px}}
main{{padding:20px 28px 60px;max-width:1100px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px}}
.card{{background:#151b2b;border:1px solid #232838;border-radius:10px;padding:14px}}
.card .k{{font-size:12px;color:#8b97b0}} .card .v{{font-size:22px;font-weight:650;margin-top:6px}}
table{{width:100%;border-collapse:collapse;font-size:13px;background:#151b2b;
border:1px solid #232838;border-radius:10px;overflow:hidden}}
th,td{{text-align:left;padding:9px 12px;border-bottom:1px solid #232838}}
th{{background:#1a2133;color:#9fb4d8;font-weight:600}}
.muted{{color:#7c89a3;text-align:center;padding:18px}}
.badge{{display:inline-block;padding:2px 10px;border-radius:999px;background:#1e2a44;
color:#8fb7ff;font-size:12px;margin-left:8px}}
.overflow{{overflow-x:auto}}
footer{{color:#5f6b83;font-size:12px;padding:0 28px 40px}}
</style></head>
<body>
<header>
<h1>🏢 AIコンテンツ販売会社 — ダッシュボード</h1>
<div class="sub">目標購入率 {s['target_conversion_rate']:.0%}
<span class="badge">{target_badge}</span> ·
損益分岐 {s['breakeven_product_count']} 商品 ·
実験進捗 {exp['created']}/{exp['target_products']}</div>
</header>
<main>
<h2>経営 KPI (§25)</h2>
<div class="grid">{kpi_cards}</div>

<h2>商品ランキング (§25)</h2>
<div class="overflow">{_table(["タイトル","カテゴリ","売上(円)","PV","購入率","評価"], ranking_rows)}</div>

<h2>AI組織 — タスク状況 (§25)</h2>
<div class="overflow">{_table(["ステータス","件数"], task_rows)}</div>

<h2>承認待ち (§21)</h2>
<div class="overflow">{_table(["種別","内容","ID"], pending_rows)}</div>

<h2>実験カテゴリー (§10, §11)</h2>
<div class="overflow">{_table(["カテゴリー","購入数合計","判定"], cat_rows)}</div>

<h2>コスト (§25, §37) — Tier別</h2>
<div class="overflow">{_table(["Tier","units"], tier_rows)}</div>
<h2>コスト — Agent別</h2>
<div class="overflow">{_table(["Agent","units"], agent_rows)}</div>
</main>
<footer>ロードマップ §25 に基づく静的ダッシュボード。data/ から生成。</footer>
</body></html>"""


def write(company: Company, path: str) -> str:
    import pathlib
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render(company), encoding="utf-8")
    return str(p)
