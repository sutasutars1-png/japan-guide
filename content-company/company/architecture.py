"""システム全体像ビュー (§25, §3.3)。

役割（AIエージェント）・稼働状況・データフローを一枚で俯瞰するダッシュボード。
`page()` が独立HTMLを返し（GUI から iframe で埋め込む）、そのページが `/api/arch`
を定期取得して、稼働中ロールの発光・承認待ち・ライブ統計を実データで更新する。
標準ライブラリのみ・外部通信なし。
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

# 表示ノード role → 担当 agent（tasks.agent と対応）。
_ROLE_AGENT = {
    "ceo": "ceo", "researcher": "researcher", "cpo": "cpo",
    "writer": "writer", "reviewer": "reviewer",
    "analyst": "analyst", "growth": "growth",
}
# 稼働中とみなす条件: 進行中(doing/todo)かつ開始が STALE 以内、または直近 AFTERGLOW
# 秒に完了した（余韻）。クラッシュで doing のまま残ったタスクは stale として除外。
_STALE_SEC = 900      # これより古い doing は「止まっている」とみなす
_AFTERGLOW_SEC = 15   # 完了直後だけ短く光らせる


def _recent(iso: str | None, secs: int) -> bool:
    if not iso:
        return False
    try:
        t = _dt.datetime.fromisoformat(iso)
    except ValueError:
        return False
    now = _dt.datetime.now(t.tzinfo)
    return (now - t).total_seconds() <= secs


def state(company) -> dict[str, Any]:
    """各ロールの稼働状況とパイプラインのライブ統計を返す。"""
    tasks = company.storage.all("tasks")
    roles: dict[str, dict[str, Any]] = {}
    for role, agent in _ROLE_AGENT.items():
        mine = [t for t in tasks if t.get("agent") == agent]
        active = False
        if mine:
            latest = max(mine, key=lambda t: t.get("created_at", ""))
            status = latest.get("status")
            if status in ("doing", "todo") and _recent(latest.get("created_at"), _STALE_SEC):
                active = True  # 実際に進行中（古すぎる doing は除外）
            elif status == "done" and _recent(latest.get("completed_at"), _AFTERGLOW_SEC):
                active = True  # 完了直後の余韻だけ
        roles[role] = {"active": active, "count": len(mine)}

    products = company.storage.all("products")

    def _n(status: str) -> int:
        return sum(1 for p in products if p.get("status") == status)

    pending_pub = [a for a in company.approvals.pending()
                   if a.get("kind") == "publish"]
    kpi = company.kpi.summary()
    improvements_new = sum(1 for r in company.storage.all("improvements")
                           if r.get("status") == "new")
    lessons = sum(1 for r in company.storage.all("lessons") if r.get("active"))
    return {
        "roles": roles,
        "human_waiting": len(pending_pub) > 0,
        "stats": {
            "tasks_today": company.cost.tasks_today(),
            "await": _n("awaiting_approval"),
            "review": _n("review"),
            "published": _n("published"),
            "lessons": lessons,
            "improvements_new": improvements_new,
            "revenue": kpi.get("total_revenue_jpy", 0),
        },
        "ts": _dt.datetime.now(_dt.timezone.utc).strftime("%H:%M:%S"),
    }


def page() -> str:
    """全体像の独立HTMLページ（ダークUI・アニメーション）。"""
    return _PAGE


# NOTE: CSS に波括弧が多いため f-string は使わない（ライブ値は /api/arch で注入）。
_PAGE = r"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>会社OS 全体像</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Michroma&family=Zen+Kaku+Gothic+New:wght@400;500;700;900&family=DM+Mono:wght@400;500&display=swap">
<style>
  :root{
    --bg:#05070d; --bg2:#080c15; --panel:#0b111d; --panel2:#0e1626;
    --line:#1b2740; --ink:#eaf1ff; --muted:#8a9ac0; --dim:#5b6a8f;
    --cyan:#38bdf8; --violet:#a78bfa; --amber:#fbbf24; --rose:#fb7185;
    --emerald:#34d399; --sky:#7dd3fc; --magenta:#e879f9; --wire:rgba(150,170,210,.16);
    --live:#34d399; --wait:#fbbf24;
  }
  *{box-sizing:border-box} html,body{margin:0}
  body{
    background:
      radial-gradient(900px 520px at 78% -8%, rgba(56,189,248,.10), transparent 60%),
      radial-gradient(760px 520px at 12% 116%, rgba(232,121,249,.08), transparent 60%),
      var(--bg);
    color:var(--ink); font-family:"Zen Kaku Gothic New", system-ui, sans-serif;
    -webkit-font-smoothing:antialiased; padding:24px 20px 40px;
  }
  .wrap{max-width:1220px;margin:0 auto}
  .eyebrow{font-family:"Michroma",sans-serif;font-size:11px;letter-spacing:.4em;color:var(--sky);
    text-transform:uppercase;display:flex;align-items:center;gap:12px}
  .eyebrow::before{content:"";width:34px;height:1px;background:linear-gradient(90deg,var(--sky),transparent)}
  h1{font-weight:900;font-size:clamp(24px,3.6vw,38px);margin:.3em 0 .1em;line-height:1.05}
  h1 .thin{font-weight:500;color:var(--muted)}
  .up{float:right;font-family:"DM Mono",monospace;font-size:11px;color:var(--dim);margin-top:8px}
  .up b{color:var(--emerald)}
  .stage{margin-top:14px;border:1px solid var(--line);border-radius:20px;
    background:linear-gradient(180deg,rgba(20,30,52,.35),rgba(8,12,20,.5)),var(--bg2);
    box-shadow:0 30px 80px -40px rgba(0,0,0,.9),inset 0 1px 0 rgba(255,255,255,.03);
    padding:10px;position:relative;overflow:hidden}
  .grid-bg{position:absolute;inset:0;opacity:.5;pointer-events:none;
    background-image:linear-gradient(var(--line) 1px,transparent 1px),linear-gradient(90deg,var(--line) 1px,transparent 1px);
    background-size:42px 42px;mask-image:radial-gradient(120% 100% at 50% 0%,#000 55%,transparent 100%)}
  svg{display:block;width:100%;height:auto;position:relative}
  .card{fill:url(#cardfill);stroke:var(--stroke,#22314f);stroke-width:1.2}
  .name{font-weight:700;font-size:19px;fill:var(--ink)}
  .fn{font-size:11.5px;fill:var(--muted);font-weight:500}
  .code{font-family:"Michroma",sans-serif;font-size:8.5px;letter-spacing:.16em;fill:var(--c);opacity:.85}
  .tag{fill:var(--c)}
  .caption{font-size:12.5px;fill:var(--muted);font-weight:500}
  .caption.k{fill:var(--dim);font-family:"DM Mono",monospace;font-size:10.5px}
  .wire{fill:none;stroke:var(--wire);stroke-width:1.6}
  /* 既定は「停止」＝流れない・薄い。稼働中の経路だけ .on で流す。 */
  .flow{fill:none;stroke-width:3.4;stroke-linecap:round;stroke-dasharray:0.5 15;
    animation:dash 2.6s linear infinite;animation-play-state:paused;opacity:.16}
  .flow.on{animation-play-state:running;opacity:1}
  .flow.s2{animation-duration:3.4s} .flow.s3{animation-duration:2.0s}
  .meta{stroke-width:2;stroke-dasharray:5 9;animation:dash 4.2s linear infinite;
    animation-play-state:paused;opacity:.22}
  .meta.on{animation-play-state:running;opacity:.85}
  .human{stroke-dasharray:4 8;stroke-width:2.6}
  @keyframes dash{to{stroke-dashoffset:-155}}
  .led.wait-anim{animation:blink 1.5s ease-in-out infinite}
  .halo{fill:none;stroke:var(--c);stroke-width:1.4;opacity:0;transform-box:fill-box;transform-origin:center}
  .node.live .halo{animation:halo 2.1s ease-in-out infinite}
  .node.live .card{stroke:var(--c);filter:drop-shadow(0 0 10px color-mix(in srgb,var(--c) 45%,transparent))}
  .node.live .statusled{fill:var(--live)}
  @keyframes halo{0%,100%{opacity:0;transform:scale(.98)}50%{opacity:.55;transform:scale(1.04)}}
  @keyframes blink{0%,100%{opacity:.25}50%{opacity:1}}
  .cnt{font-family:"DM Mono",monospace;font-size:10px;fill:var(--dim)}
  .foot{display:flex;flex-wrap:wrap;gap:10px 24px;align-items:center;margin:14px 4px 0;color:var(--muted);font-size:12.5px}
  .lg{display:inline-flex;align-items:center;gap:8px}
  .dot{width:9px;height:9px;border-radius:50%;display:inline-block}
  .ln{width:26px;border-top:3px dotted var(--sky)} .ln.dash{border-top:2px dashed var(--magenta)}
  .stats{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin-top:16px}
  @media(max-width:760px){.stats{grid-template-columns:repeat(3,1fr)}}
  .tile{border:1px solid var(--line);border-radius:13px;background:linear-gradient(180deg,var(--panel2),var(--panel));
    padding:12px 14px;position:relative;overflow:hidden}
  .tile::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--c)}
  .tile .v{font-family:"DM Mono",monospace;font-weight:500;font-size:22px;font-variant-numeric:tabular-nums}
  .tile .l{font-size:11px;color:var(--muted);margin-top:2px}
  .os{margin-top:20px}
  .os h2{font-family:"Michroma",sans-serif;font-size:11px;letter-spacing:.32em;color:var(--dim);text-transform:uppercase;margin:0 0 12px 2px}
  .chips{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
  @media(max-width:720px){.chips{grid-template-columns:repeat(2,1fr)}}
  .chip{border:1px solid var(--line);border-radius:13px;background:linear-gradient(180deg,var(--panel2),var(--panel));
    padding:12px 14px;display:flex;flex-direction:column;gap:3px;position:relative;overflow:hidden}
  .chip::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--c)}
  .chip .t{font-weight:700;font-size:14px} .chip .s{font-size:11px;color:var(--muted)}
  .chip .en{position:absolute;right:10px;top:9px;font-family:"Michroma",sans-serif;font-size:8px;letter-spacing:.14em;color:var(--dim)}
  .note{margin:18px 4px 0;color:var(--dim);font-size:12px;font-family:"DM Mono",monospace}
  @media (prefers-reduced-motion: reduce){
    .flow,.meta{animation:none;stroke-dasharray:1 12;opacity:.16}
    .flow.on,.meta.on{opacity:1}
    .node.live .halo{animation:none;opacity:.4} .led.wait-anim{animation:none;opacity:.9}
  }
</style></head><body>
<div class="wrap">
  <div class="up">LIVE · 最終更新 <b id="ts">--:--:--</b></div>
  <div class="eyebrow">System Architecture</div>
  <h1>AI自律型note運営会社 <span class="thin">／ 会社OS 全体像</span></h1>

  <div class="stage">
    <div class="grid-bg"></div>
    <svg viewBox="0 0 1280 760" role="img" aria-label="会社OSの役割とデータフローの全体図">
      <defs>
        <linearGradient id="cardfill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="#111b30"/><stop offset="1" stop-color="#0a1120"/>
        </linearGradient>
        <path id="p_ceo_plan"  d="M640,131 C 560,180 470,205 400,247"/>
        <path id="p_ceo_res"   d="M640,131 C 430,178 250,210 150,247"/>
        <path id="p_res_plan"  d="M238,300 L 312,300"/>
        <path id="p_plan_wr"   d="M488,300 L 562,300"/>
        <path id="p_wr_rev"    d="M738,300 L 797,300"/>
        <path id="p_rev_appr"  d="M973,300 L 1032,300"/>
        <path id="p_appr_pub"  d="M1120,335 L 1120,465"/>
        <path id="p_pub_met"   d="M1032,500 L 958,500"/>
        <path id="p_met_eva"   d="M782,500 L 708,500"/>
        <path id="p_eva_plan"  d="M560,478 C 470,430 430,380 400,337"/>
        <path id="p_loop"      d="M885,337 C 885,412 650,412 650,337"/>
        <path id="p_eva_grow"  d="M620,535 L 620,623"/>
        <path id="p_grow_appr" d="M708,660 C 980,660 1120,520 1120,338"/>
        <path id="p_pub_ch"    d="M1120,535 L 1120,592"/>
        <path id="p_human_fix" d="M1032,283 C 900,205 730,205 650,263"/>
      </defs>
      <use href="#p_ceo_plan" class="wire"/><use href="#p_ceo_res" class="wire"/>
      <use href="#p_res_plan" class="wire"/><use href="#p_plan_wr" class="wire"/>
      <use href="#p_wr_rev" class="wire"/><use href="#p_rev_appr" class="wire"/>
      <use href="#p_appr_pub" class="wire"/><use href="#p_pub_met" class="wire"/>
      <use href="#p_met_eva" class="wire"/><use href="#p_eva_plan" class="wire"/>
      <use href="#p_loop" class="wire"/><use href="#p_eva_grow" class="wire"/>
      <use href="#p_grow_appr" class="wire"/><use href="#p_pub_ch" class="wire"/>
      <use href="#p_human_fix" class="wire"/>
      <use href="#p_ceo_plan" class="flow s2" data-drive="ceo" style="stroke:var(--violet)"/>
      <use href="#p_ceo_res"  class="flow s2" data-drive="ceo" style="stroke:var(--cyan)"/>
      <use href="#p_res_plan" class="flow" data-drive="researcher" style="stroke:var(--cyan)"/>
      <use href="#p_plan_wr"  class="flow" data-drive="cpo" style="stroke:var(--violet)"/>
      <use href="#p_wr_rev"   class="flow s3" data-drive="writer" style="stroke:var(--amber)"/>
      <use href="#p_rev_appr" class="flow" data-drive="reviewer" style="stroke:var(--rose)"/>
      <use href="#p_appr_pub" class="flow" data-drive="human" style="stroke:var(--emerald)"/>
      <use href="#p_pub_met"  class="flow" data-drive="analyst" style="stroke:var(--sky)"/>
      <use href="#p_met_eva"  class="flow" data-drive="analyst" style="stroke:var(--sky)"/>
      <use href="#p_eva_plan" class="flow s2" data-drive="analyst" style="stroke:var(--emerald)"/>
      <use href="#p_loop"     class="flow s3" data-drive="writer" style="stroke:var(--amber)"/>
      <use href="#p_eva_grow" class="flow s2" data-drive="growth" style="stroke:var(--magenta)"/>
      <use href="#p_grow_appr" class="meta" data-drive="growth" style="stroke:var(--magenta)"/>
      <use href="#p_pub_ch"   class="flow s2" data-drive="growth" style="stroke:var(--sky)"/>
      <use href="#p_human_fix" class="flow s2 human" data-drive="human" style="stroke:var(--emerald)"/>
      <text class="caption" x="838" y="198" text-anchor="middle" fill="#8fe6bf">人間の差し戻し・修正指示</text>
      <text class="caption" x="767" y="404" text-anchor="middle" fill="#c9b27a">自動再執筆（最大4回）</text>
      <text class="caption" x="452" y="410" text-anchor="middle" fill="#9fe6c2">学習：教訓・実績を反映</text>
      <text class="caption" x="1120" y="404" text-anchor="middle" fill="#f0abfc">システム改修提案</text>
      <text class="caption k" x="1120" y="420" text-anchor="middle">人間が採否を判断</text>
      <text class="caption k" x="1120" y="356" text-anchor="middle" fill="#7fe6b8">人間 GO</text>

      <g class="node" id="n-ceo" data-role="ceo" style="--c:var(--violet);--stroke:#3a2f66">
        <rect class="halo" x="548" y="53" width="184" height="78" rx="19"/>
        <rect class="card" x="552" y="57" width="176" height="70" rx="16"/>
        <circle class="tag" cx="574" cy="80" r="4"/>
        <text class="code" x="712" y="76" text-anchor="end">CEO</text>
        <text class="name" x="586" y="88">経営</text>
        <text class="fn" x="586" y="108">実験配分・意思決定</text>
        <text class="cnt" id="c-ceo" x="712" y="112" text-anchor="end"></text>
        <circle class="statusled" cx="574" cy="108" r="4.5" fill="var(--dim)"/>
      </g>
      <g class="node" id="n-researcher" data-role="researcher" style="--c:var(--cyan);--stroke:#1d3a55">
        <rect class="halo" x="58" y="261" width="184" height="78" rx="19"/>
        <rect class="card" x="62" y="265" width="176" height="70" rx="16"/>
        <circle class="tag" cx="84" cy="288" r="4"/>
        <text class="code" x="222" y="284" text-anchor="end">RESEARCH</text>
        <text class="name" x="96" y="296">調査</text>
        <text class="fn" x="96" y="316">市場・需要リサーチ</text>
        <text class="cnt" id="c-researcher" x="222" y="320" text-anchor="end"></text>
        <circle class="statusled" cx="84" cy="314" r="4.5" fill="var(--dim)"/>
      </g>
      <g class="node" id="n-cpo" data-role="cpo" style="--c:var(--violet);--stroke:#3a2f66">
        <rect class="halo" x="308" y="261" width="184" height="78" rx="19"/>
        <rect class="card" x="312" y="265" width="176" height="70" rx="16"/>
        <circle class="tag" cx="334" cy="288" r="4"/>
        <text class="code" x="472" y="284" text-anchor="end">PLAN</text>
        <text class="name" x="346" y="296">企画</text>
        <text class="fn" x="346" y="316">商品設計・仮説立案</text>
        <text class="cnt" id="c-cpo" x="472" y="320" text-anchor="end"></text>
        <circle class="statusled" cx="334" cy="314" r="4.5" fill="var(--dim)"/>
      </g>
      <g class="node" id="n-writer" data-role="writer" style="--c:var(--amber);--stroke:#5a4a1f">
        <rect class="halo" x="558" y="261" width="184" height="78" rx="19"/>
        <rect class="card" x="562" y="265" width="176" height="70" rx="16"/>
        <circle class="tag" cx="584" cy="288" r="4"/>
        <text class="code" x="722" y="284" text-anchor="end">WRITE</text>
        <text class="name" x="596" y="296">執筆</text>
        <text class="fn" x="596" y="316">記事の本文生成</text>
        <text class="cnt" id="c-writer" x="722" y="320" text-anchor="end"></text>
        <circle class="statusled" cx="584" cy="314" r="5" fill="var(--dim)"/>
      </g>
      <g class="node" id="n-reviewer" data-role="reviewer" style="--c:var(--rose);--stroke:#5a2436">
        <rect class="halo" x="793" y="261" width="184" height="78" rx="19"/>
        <rect class="card" x="797" y="265" width="176" height="70" rx="16"/>
        <circle class="tag" cx="819" cy="288" r="4"/>
        <text class="code" x="957" y="284" text-anchor="end">REVIEW</text>
        <text class="name" x="831" y="296">レビュー</text>
        <text class="fn" x="831" y="316">品質・法務チェック</text>
        <text class="cnt" id="c-reviewer" x="957" y="320" text-anchor="end"></text>
        <circle class="statusled" cx="819" cy="314" r="5" fill="var(--dim)"/>
      </g>
      <g class="node" id="n-human" data-role="human" style="--c:var(--emerald);--stroke:#1f4d3c">
        <rect class="halo" x="1028" y="261" width="184" height="78" rx="19"/>
        <rect class="card" x="1032" y="265" width="176" height="70" rx="16"/>
        <circle class="tag" cx="1054" cy="288" r="4"/>
        <text class="code" x="1192" y="284" text-anchor="end">APPROVE · 人間</text>
        <text class="name" x="1066" y="296">承認</text>
        <text class="fn" x="1066" y="316">公開可否を人が判断</text>
        <circle class="led" id="led-human" cx="1054" cy="314" r="5" fill="var(--dim)"/>
      </g>
      <g class="node" id="n-publish" data-role="publish" style="--c:var(--sky);--stroke:#1d3d55">
        <rect class="halo" x="1028" y="461" width="184" height="78" rx="19"/>
        <rect class="card" x="1032" y="465" width="176" height="70" rx="16"/>
        <circle class="tag" cx="1054" cy="488" r="4"/>
        <text class="code" x="1192" y="484" text-anchor="end">PUBLISH</text>
        <text class="name" x="1066" y="496">公開</text>
        <text class="fn" x="1066" y="516">note へ記事＋サムネ</text>
        <circle class="statusled" cx="1054" cy="514" r="4.5" fill="var(--dim)"/>
      </g>
      <g class="node" id="n-metrics" data-role="metrics" style="--c:var(--sky);--stroke:#1d3d55">
        <rect class="halo" x="778" y="461" width="184" height="78" rx="19"/>
        <rect class="card" x="782" y="465" width="176" height="70" rx="16"/>
        <circle class="tag" cx="804" cy="488" r="4"/>
        <text class="code" x="942" y="484" text-anchor="end">METRICS</text>
        <text class="name" x="816" y="496">実績取込</text>
        <text class="fn" x="816" y="516">売上・PV を反映</text>
        <circle class="statusled" cx="804" cy="514" r="4.5" fill="var(--dim)"/>
      </g>
      <g class="node" id="n-analyst" data-role="analyst" style="--c:var(--emerald);--stroke:#1f4d3c">
        <rect class="halo" x="528" y="461" width="184" height="78" rx="19"/>
        <rect class="card" x="532" y="465" width="176" height="70" rx="16"/>
        <circle class="tag" cx="554" cy="488" r="4"/>
        <text class="code" x="692" y="484" text-anchor="end">EVALUATE</text>
        <text class="name" x="566" y="496">評価・分析</text>
        <text class="fn" x="566" y="516">成功/失敗と次の一手</text>
        <circle class="statusled" cx="554" cy="514" r="4.5" fill="var(--dim)"/>
      </g>
      <g class="node" id="n-growth" data-role="growth" style="--c:var(--magenta);--stroke:#4a2350">
        <rect class="halo" x="528" y="621" width="184" height="78" rx="19"/>
        <rect class="card" x="532" y="625" width="176" height="70" rx="16"/>
        <circle class="tag" cx="554" cy="648" r="4"/>
        <text class="code" x="692" y="644" text-anchor="end">GROWTH</text>
        <text class="name" x="566" y="656">グロース</text>
        <text class="fn" x="566" y="676">改善・システム改修提案</text>
        <text class="cnt" id="c-growth" x="692" y="680" text-anchor="end"></text>
        <circle class="statusled" cx="554" cy="674" r="4.5" fill="var(--dim)"/>
      </g>
      <g>
        <text class="caption k" x="1120" y="612" text-anchor="middle" fill="#9fb0d0">マーケ：SNS下書き（投稿は人間）</text>
        <g font-size="12" font-weight="700" text-anchor="middle">
          <rect x="1024" y="624" width="60" height="30" rx="9" fill="#0d1830" stroke="#1d3d55"/>
          <text x="1054" y="643" fill="var(--sky)">note</text>
          <rect x="1090" y="624" width="60" height="30" rx="9" fill="#0d1830" stroke="#2a2350"/>
          <text x="1120" y="643" fill="var(--violet)">X下書</text>
          <rect x="1156" y="624" width="64" height="30" rx="9" fill="#0d1830" stroke="#3a2340"/>
          <text x="1188" y="643" fill="var(--magenta)">TikTok</text>
        </g>
      </g>
    </svg>
  </div>

  <div class="foot">
    <span class="lg"><span class="dot" style="background:var(--emerald);box-shadow:0 0 8px var(--emerald)"></span>稼働中（発光）</span>
    <span class="lg"><span class="dot" style="background:var(--wait)"></span>承認待ち（点滅）</span>
    <span class="lg"><span class="dot" style="background:var(--dim)"></span>待機</span>
    <span class="lg"><span class="ln"></span>データの流れ（稼働中の経路だけ点が流れる）</span>
    <span class="lg"><span class="ln dash"></span>提案（人間が承認）</span>
  </div>

  <div class="stats">
    <div class="tile" style="--c:var(--sky)"><div class="v" id="st-tasks">0</div><div class="l">本日タスク</div></div>
    <div class="tile" style="--c:var(--emerald)"><div class="v" id="st-await">0</div><div class="l">公開待ち</div></div>
    <div class="tile" style="--c:var(--rose)"><div class="v" id="st-review">0</div><div class="l">差し戻し中</div></div>
    <div class="tile" style="--c:var(--cyan)"><div class="v" id="st-pub">0</div><div class="l">公開済</div></div>
    <div class="tile" style="--c:var(--amber)"><div class="v" id="st-lessons">0</div><div class="l">教訓</div></div>
    <div class="tile" style="--c:var(--magenta)"><div class="v" id="st-improve">0</div><div class="l">改修提案(新規)</div></div>
  </div>

  <div class="os">
    <h2>OS 基盤 — 全役割が共有する土台</h2>
    <div class="chips">
      <div class="chip" style="--c:var(--cyan)"><span class="en">MEMORY</span><span class="t">記憶</span><span class="s">経験・成功/失敗の蓄積</span></div>
      <div class="chip" style="--c:var(--violet)"><span class="en">ROUTER</span><span class="t">モデル振分</span><span class="s">必要な所だけ高性能</span></div>
      <div class="chip" style="--c:var(--amber)"><span class="en">COST</span><span class="t">コスト管理</span><span class="s">1日タスク上限・予算</span></div>
      <div class="chip" style="--c:var(--emerald)"><span class="en">APPROVAL</span><span class="t">承認ゲート</span><span class="s">重要操作は人間承認</span></div>
      <div class="chip" style="--c:var(--sky)"><span class="en">TASK</span><span class="t">タスク管理</span><span class="s">工程を秩序立てて実行</span></div>
      <div class="chip" style="--c:var(--rose)"><span class="en">KPI · EXP</span><span class="t">KPI・実験</span><span class="s">20商品実験・撤退基準</span></div>
      <div class="chip" style="--c:var(--magenta)"><span class="en">SKILL LAB</span><span class="t">Skill自己改善</span><span class="s">教訓→改善案→採用</span></div>
      <div class="chip" style="--c:var(--amber)"><span class="en">QUALITY</span><span class="t">品質ガード</span><span class="s">体裁・価格連動・重複</span></div>
    </div>
  </div>
  <p class="note">※ 稼働中／承認待ちは実際のタスク状況に連動（約4秒ごと更新）。売上等は実績取込後に反映されます。</p>
</div>
<script>
  const yen=n=>'¥'+(n||0).toLocaleString('ja-JP');
  async function tick(){
    try{
      const r=await fetch('/api/arch'); const s=await r.json();
      for(const [role,info] of Object.entries(s.roles||{})){
        const el=document.getElementById('n-'+role);
        if(el) el.classList.toggle('live', !!info.active);
        const c=document.getElementById('c-'+role);
        if(c) c.textContent = info.count? ('×'+info.count):'';
      }
      // フロー線は「稼働中の経路だけ」流す。駆動役割が動いていなければ静止。
      const roles=s.roles||{};
      const on=d=> d==='human' ? !!s.human_waiting : !!(roles[d] && roles[d].active);
      document.querySelectorAll('[data-drive]').forEach(el=>{
        el.classList.toggle('on', on(el.getAttribute('data-drive')));
      });
      const led=document.getElementById('led-human');
      if(led){ led.setAttribute('fill', s.human_waiting? 'var(--wait)':'var(--dim)');
        led.classList.toggle('wait-anim', !!s.human_waiting);
        const hn=document.getElementById('n-human'); if(hn) hn.classList.remove('live');
      }
      const st=s.stats||{};
      const set=(id,v)=>{const e=document.getElementById(id); if(e) e.textContent=v;};
      set('st-tasks',st.tasks_today||0); set('st-await',st.await||0);
      set('st-review',st.review||0); set('st-pub',st.published||0);
      set('st-lessons',st.lessons||0); set('st-improve',st.improvements_new||0);
      set('ts', s.ts||'');
    }catch(e){/* オフライン時は前回表示を維持 */}
  }
  tick(); setInterval(tick, 4000);
</script>
</body></html>
"""
