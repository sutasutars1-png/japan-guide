"""ローカル Web GUI（標準ライブラリ http.server のみ）。

`python3 -m company gui` で起動し、ブラウザから会社 OS を操作する。npm も外部
パッケージも不要（§36）。人間の役割＝経営判断・承認（§3.3, §21）に集中できる
よう、**承認待ち**と**次アクション**を中心に据えたコックピット。

エンドポイント（すべて 127.0.0.1 既定）:
  GET  /                     コックピット HTML
  GET  /dashboard            §25 ダッシュボード（iframe 埋め込み用）
  GET  /api/state            KPI・進捗・承認待ち・商品・スキル をまとめて返す
  GET  /api/article?product_id=  記事本文（body_markdown 等）を返す（確認用）
  POST /api/plan             {n, llm}   企画パイプライン実行
  POST /api/approve|reject   {approval_id}
  POST /api/publish          {product_id, url, approval_id}
  POST /api/metrics          {product_id, pv, purchases, revenue, likes, rating}
  POST /api/evaluate         {}
  POST /api/demo             {}
  GET  /api/report?period=
  GET  /api/memory?query=&kind=
  POST /api/skill/propose|evaluate|request-adoption|adopt
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import html as _html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import dashboard
from .approval import PermissionError_
from .company import Company


def _state(c: Company) -> dict:
    products = c.storage.all("products")
    pending = c.approvals.pending()
    # product_id → 最新の publish 承認 {id, status}（pending だけでなく承認済みも）。
    # 承認後も承認IDを行に残し、「公開URL記録」ボタンを出せるようにする。
    pub_apr: dict = {}
    for a in c.storage.all("approvals"):
        if a.get("kind") != "publish":
            continue
        pid = a.get("payload", {}).get("product_id")
        if pid:
            pub_apr[pid] = {"id": a["id"], "status": a.get("status", "pending")}
    prod_rows = [{
        "id": p["id"], "title": p.get("title"), "category": p.get("category"),
        "status": p.get("status"), "pv": p.get("pv", 0),
        "purchases": p.get("purchases", 0), "revenue_jpy": p.get("revenue_jpy", 0),
        "conversion_rate": p.get("conversion_rate", 0), "outcome": p.get("outcome"),
        "url": p.get("url"),
        "approval_id": (pub_apr.get(p["id"]) or {}).get("id"),
        "approval_status": (pub_apr.get(p["id"]) or {}).get("status"),
        "pending_feedback": p.get("pending_feedback", ""),
    } for p in products]
    prod_rows.sort(key=lambda r: (r["status"] != "awaiting_approval", r["id"]))
    social = c.social.list()
    return {
        "summary": c.kpi.summary(),
        "progress": c.experiments.progress(),
        "pending": pending,
        "products": prod_rows,
        "skills": c.skills_lab.all_current(),
        "lessons": sorted(
            ({"skill": r.get("skill"), "guideline": r.get("guideline"),
              "count": r.get("count", 0)}
             for r in c.storage.all("lessons") if r.get("active")),
            key=lambda x: x["count"], reverse=True),
        "tasks_today": c.cost.tasks_today(),
        "max_tasks_per_day": c.config.max_tasks_per_day,
        "runner": type(c.tasks.runner).__name__,
        # 配信中の画面HTMLの内容ハッシュ。git pull 後に再起動したかを一目で判別できる
        # （サーバーは起動時に _INDEX_HTML を読み込むため、再起動しないと更新されない）。
        "build": hashlib.sha1(_INDEX_HTML.encode("utf-8")).hexdigest()[:8],
        "config": c.config.editable_snapshot(),
        "schedule": c.scheduler.get_state(),
        "channels": {"x": c.config.x_enabled, "tiktok": c.config.tiktok_enabled},
        "social": social,
        "improvements": sorted(
            c.storage.all("improvements"),
            key=lambda r: ({"new": 0, "accepted": 1, "done": 2, "rejected": 3}
                           .get(r.get("status"), 9), r.get("created_at", "")),
        ),
    }


_STEP_LABEL = {
    "market-research": "調査", "product-planning": "企画",
    "article-writing": "執筆", "quality-review": "レビュー",
}


def _logs(c: Company, limit: int = 60) -> dict:
    """AI が実行したタスク（調査/企画/執筆/レビュー）を新しい順に返す。"""
    tasks = c.storage.all("tasks")
    tasks.sort(key=lambda t: t.get("created_at", ""), reverse=True)
    rows = []
    for t in tasks[:limit]:
        rows.append({
            "ts": t.get("created_at", ""),
            "agent": t.get("agent", ""),
            "step": _STEP_LABEL.get(t.get("skill", ""), t.get("skill") or t.get("title", "")),
            "status": t.get("status", ""),
            "review": t.get("review_status") or "",
            "notes": (t.get("review_notes") or t.get("title") or "")[:160],
        })
    return {"tasks": rows}


def _debug(c: Company, limit: int = 40) -> dict:
    """デバッグ用の要約診断。

    エラー / LLMフォールバック / 差し戻し / 予算上限などを新しい順に集約する。
    詳細ダンプではなく「概要が掴める」粒度。そのまま貼り付けて共有できる
    プレーンテキスト (``text``) も返し、人間が Claude に渡して検証・修正できる。
    """
    tasks = c.storage.all("tasks")
    tasks.sort(key=lambda t: t.get("created_at", ""), reverse=True)
    products = c.storage.all("products")

    runner_cls = type(c.tasks.runner).__name__
    llm_on = runner_cls == "ClaudeRunner"
    runner_label = "実LLM (Claude CLI)" if llm_on else "雛形 (Template)"

    issues: list[dict] = []

    def push(sev: str, kind: str, msg: str, ts: str = "") -> None:
        issues.append({"sev": sev, "kind": kind,
                       "msg": " ".join(str(msg).split())[:200],
                       "ts": (ts or "").replace("T", " ")[:19]})

    for t in tasks:
        out = t.get("output") if isinstance(t.get("output"), dict) else {}
        ts = t.get("created_at", "")
        title = t.get("title", "") or t.get("skill", "")
        if t.get("status") == "error":
            push("error", "タスクエラー",
                 f"{title}: {t.get('error') or out.get('_llm_error') or '不明'}", ts)
        elif out.get("_llm_error"):
            push("warn", "LLMフォールバック", f"{title}: {out.get('_llm_error')}", ts)
        if t.get("review_status") == "reject":
            push("warn", "差し戻し", f"{title}: {t.get('review_notes') or ''}", ts)

    for m in c.memory.recent(30):
        if m.get("kind") == "failure":
            push("error", "失敗記録",
                 f"{m.get('title', '')}: {m.get('body', '')}", m.get("created_at", ""))

    for p in products:
        if p.get("status") == "review" and p.get("pending_feedback"):
            push("warn", "差し戻し滞留",
                 f"{p.get('title', '')}: 人間の修正指示が未反映のまま", p.get("updated_at", ""))

    # 同じ根本原因の繰り返し（未ログイン等）を一言に集約した headline を作る。
    blob = " ".join(i["msg"].lower() for i in issues)
    n_llm_err = sum(1 for i in issues if i["kind"] in ("LLMフォールバック", "タスクエラー"))
    headline = ""
    if any(k in blob for k in ("logged in", "log in", "/login", "unauthorized")):
        headline = ("🔑 claude CLI が未ログインです。ターミナルで `claude` を起動し "
                    "`/login` でログインしてください。ログインするまで生成はすべて雛形に"
                    f"フォールバックします（該当 {n_llm_err} 件）。")
    elif "未検出" in blob or "見つかりません" in blob:
        headline = "🧩 claude CLI が見つかりません。インストールと PATH を確認してください。"
    elif "タイムアウト" in blob:
        headline = "⏱ claude CLI の応答が遅い/返りません。ネットワークやCLIの状態を確認してください。"
    elif "json 解析失敗" in blob:
        headline = f"⚠ LLM 出力の解析に失敗しています（{n_llm_err} 件）。プロンプト/出力形式を要確認。"

    issues = issues[:limit]
    counts = {
        "products": len(products),
        "await": sum(1 for p in products if p.get("status") == "awaiting_approval"),
        "review": sum(1 for p in products if p.get("status") == "review"),
        "published": sum(1 for p in products if p.get("status") == "published"),
        "tasks_today": c.cost.tasks_today(),
        "pending_approvals": len(c.approvals.pending()),
        "errors": sum(1 for i in issues if i["sev"] == "error"),
        "warns": sum(1 for i in issues if i["sev"] == "warn"),
    }

    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"# デバッグ要約 ({now})"]
    if headline:
        lines += [f"‼ 診断: {headline}", ""]
    lines += [
        f"ランナー: {runner_label}",
        f"商品 {counts['products']} / 公開待ち {counts['await']} / 差し戻し {counts['review']}"
        f" / 公開 {counts['published']}",
        f"本日タスク {counts['tasks_today']} / 承認待ち {counts['pending_approvals']}"
        f" / エラー {counts['errors']} / 警告 {counts['warns']}",
        "",
        "## 直近の問題（新しい順）",
    ]
    if issues:
        lines += [f"- [{i['sev']}] {i['kind']}: {i['msg']}"
                  + (f" ({i['ts']})" if i['ts'] else "") for i in issues]
    else:
        lines.append("- 問題は検出されていません")
    return {"runner": runner_label, "llm_on": llm_on, "headline": headline,
            "counts": counts, "issues": issues, "text": "\n".join(lines)}


def _social_preview_page(c: Company, sid: str) -> str:
    """X / TikTok 下書きの試し読みページ（投稿ごとにコピー可）。"""
    esc = _html.escape
    post = c.storage.get("social", sid)
    if not post:
        return ("<!doctype html><meta charset='utf-8'><body style='font-family:sans-serif;"
                "background:#0b0f17;color:#e8eefc;padding:24px'>下書きが見つかりません。</body>")
    content = post.get("content") or {}
    prod = c.storage.get("products", post.get("product_id")) or {}
    channel = str(post.get("channel", ""))
    ch_label = {"x": "X（旧Twitter）", "tiktok": "TikTok"}.get(channel, channel)
    texts: list[str] = []

    def cp(label: str, text: str) -> str:
        texts.append(text)
        return f'<button class="cp" data-i="{len(texts) - 1}">{esc(label)}</button>'

    sec: list[str] = []
    posts = content.get("posts")
    if isinstance(posts, list) and posts:
        for i, t in enumerate(posts, 1):
            txt = str(t)
            sec.append(f'<div class="post"><div class="ph"><b>投稿 {i}</b>'
                       f'<span class="cc">{len(txt)}字</span>{cp("コピー", txt)}</div>'
                       f'<div class="pt">{esc(txt)}</div></div>')
    if content.get("hook"):
        h = str(content["hook"])
        sec.append(f'<div class="post"><div class="ph"><b>フック（最初の3秒）</b>'
                   f'{cp("コピー", h)}</div><div class="pt">{esc(h)}</div></div>')
    script = content.get("script")
    if isinstance(script, list) and script:
        li = "".join(f"<li>{esc(str(s))}</li>" for s in script)
        full = "\n".join(str(s) for s in script)
        sec.append(f'<div class="post"><div class="ph"><b>台本</b>{cp("全部コピー", full)}</div>'
                   f'<ol class="sc">{li}</ol></div>')
    caps = content.get("captions")
    if isinstance(caps, list) and caps:
        li = "".join(f"<li>{esc(str(s))}</li>" for s in caps)
        sec.append(f'<div class="post"><div class="ph"><b>字幕案</b></div><ul class="sc">{li}</ul></div>')
    tags = content.get("hashtags")
    if isinstance(tags, list) and tags:
        tg = " ".join("#" + str(t).lstrip("#") for t in tags)
        sec.append(f'<div class="post"><div class="ph"><b>ハッシュタグ</b>{cp("コピー", tg)}</div>'
                   f'<div class="pt">{esc(tg)}</div></div>')
    if content.get("note"):
        sec.append(f'<div class="muted2">メモ: {esc(str(content["note"]))}</div>')
    if not sec:
        sec.append('<div class="muted2">下書き内容が空です（実LLM生成ONで作り直してください）。</div>')

    body = "".join(sec)
    texts_json = json.dumps(texts, ensure_ascii=False)
    title = esc(prod.get("title") or post.get("product_id") or "")
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>下書き試し読み: {ch_label}</title>
<style>
 body{{font-family:system-ui,"Segoe UI","Hiragino Kaku Gothic ProN",Meiryo,sans-serif;
   max-width:720px;margin:0 auto;padding:18px;background:#0b0f17;color:#e8eefc}}
 h1{{font-size:18px;margin:2px 0 2px}} .sub{{color:#9fb0d0;font-size:13px;margin-bottom:12px}}
 .post{{background:#0f1626;border:1px solid #24314f;border-radius:12px;padding:12px 14px;margin:10px 0}}
 .ph{{display:flex;align-items:center;gap:10px;margin-bottom:6px}}
 .ph b{{font-size:14px}} .cc{{color:#8aa0c8;font-size:12px}}
 .cp{{margin-left:auto;background:#2f6bff;color:#fff;border:0;border-radius:8px;padding:6px 12px;font-size:13px;cursor:pointer}}
 .pt{{white-space:pre-wrap;line-height:1.7;font-size:15px}}
 .sc{{margin:.2em 0 .2em 1.2em;line-height:1.7}} .sc li{{margin:.2em 0}}
 .muted2{{color:#8aa0c8;font-size:13px;margin-top:8px}}
 #msg{{color:#7fd1a6;font-size:13px;margin-left:8px}}
</style></head><body>
<h1>{ch_label} 下書き <span id="msg"></span></h1>
<div class="sub">商品: {title} ／ 投稿は人間が行います（自動投稿なし）</div>
{body}
<script>
 const TEXTS={texts_json};
 document.querySelectorAll('.cp').forEach(b=>b.onclick=async()=>{{
   const t=TEXTS[+b.dataset.i]||'';
   try{{await navigator.clipboard.writeText(t);document.getElementById('msg').textContent='コピーしました';}}
   catch(e){{document.getElementById('msg').textContent='コピー不可（手動選択してください）';}}
 }});
</script></body></html>"""


def _note_preview_page(c: Company, product_id: str) -> str:
    """note 貼り付け用プレビュー（書式ごとコピー可能な独立ページ）。"""
    try:
        data = c.note_export.render_html(product_id)
    except Exception as exc:  # noqa: BLE001
        return ("<!doctype html><meta charset='utf-8'><body style='font-family:sans-serif;"
                "padding:24px'>記事を取得できませんでした: " + _html.escape(str(exc))
                + "<br>（実 LLM 生成で記事を作成し、レビュー通過した商品を選んでください）</body>")
    tags = " ".join("#" + t for t in data.get("hashtags", []))
    title = _html.escape(data.get("title") or "")
    price = data.get("price_jpy")
    body_html = data.get("html", "")
    tags_esc = _html.escape(tags)
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>note貼り付け用: {title}</title>
<style>
 body{{font-family:system-ui,"Segoe UI",Roboto,sans-serif;max-width:760px;margin:0 auto;
   padding:20px;background:#0b0f17;color:#e8eefc}}
 .bar{{position:sticky;top:0;background:#0b0f17;padding:12px 0;border-bottom:1px solid #24314f;
   display:flex;gap:10px;align-items:center;flex-wrap:wrap;z-index:5}}
 button{{background:#2f6bff;color:#fff;border:0;border-radius:8px;padding:9px 14px;
   font-size:14px;cursor:pointer}} button.ghost{{background:#1e2a44;color:#cfe0ff}}
 .muted{{color:#9fb0d0;font-size:13px}} .tags{{color:#7fd1a6;font-size:13px;margin-top:4px}}
 #doc{{background:#0f1626;border:1px solid #24314f;border-radius:10px;padding:22px;margin-top:14px;
   line-height:1.9}}
 #doc h1{{font-size:1.6em;margin:.2em 0 .5em}} #doc h2{{font-size:1.3em;margin:1.1em 0 .4em;
   border-bottom:1px solid #24314f;padding-bottom:4px}} #doc h3{{font-size:1.12em;margin:1em 0 .3em}}
 #doc p{{margin:.7em 0}} #doc ul,#doc ol{{margin:.6em 0 .6em 1.4em}} #doc li{{margin:.25em 0}}
 #doc hr{{border:0;border-top:2px dashed #3a4a70;margin:1.4em 0}}
 #doc .paid{{color:#ffcf6b;font-weight:700}} #doc blockquote{{border-left:3px solid #3a4a70;
   margin:.6em 0;padding:.2em .9em;color:#c7d4ef}}
 #msg{{margin-left:auto;color:#7fd1a6;font-size:13px}}
</style></head><body>
<div class="bar">
  <button id="copyBtn">📋 書式ごとコピー</button>
  <button class="ghost" id="copyText">テキストのみコピー</button>
  <span class="muted">→ note の本文に貼り付け（見出し・太字・箇条書きが保持されます）</span>
  <span id="msg"></span>
</div>
<div class="thumb">
  <div class="muted" style="margin-bottom:6px">note サムネイル（成果物）:</div>
  <img id="thumbImg" src="/note/thumb.svg?product_id={_html.escape(product_id)}"
       alt="thumbnail" style="max-width:100%;border:1px solid #24314f;border-radius:10px">
  <div class="row" style="margin-top:8px">
    <button id="thumbPng">🖼 サムネをPNG保存（1280×670）</button>
    <span class="muted">note のヘッダ画像にアップロードできます</span>
  </div>
</div>
<div class="muted" style="margin-top:14px">価格: {price}円 ／ ハッシュタグ:</div>
<div class="tags">{tags_esc}</div>
<p class="muted">点線（👇 ここから下を…）の位置に、note 側で「有料エリア」の区切りを設定してください。
自動投稿はしません（貼り付け・公開は人間, §22）。</p>
<div id="doc">{body_html}</div>
<script>
 const msg=t=>{{document.getElementById('msg').textContent=t;}};
 const doc=document.getElementById('doc');
 document.getElementById('copyBtn').onclick=async()=>{{
   try{{
     await navigator.clipboard.write([new ClipboardItem({{
       'text/html': new Blob([doc.innerHTML],{{type:'text/html'}}),
       'text/plain': new Blob([doc.innerText],{{type:'text/plain'}})
     }})]);
     msg('コピーしました。noteに貼り付けてください。');
   }}catch(e){{
     const r=document.createRange(); r.selectNodeContents(doc);
     const sel=getSelection(); sel.removeAllRanges(); sel.addRange(r);
     try{{document.execCommand('copy'); msg('コピーしました（選択方式）。');}}
     catch(_){{msg('自動コピー不可。本文を手動で全選択してコピーしてください。');}}
   }}
 }};
 document.getElementById('copyText').onclick=async()=>{{
   try{{await navigator.clipboard.writeText(doc.innerText);msg('テキストをコピーしました。');}}
   catch(e){{msg('自動コピー不可。手動で選択してください。');}}
 }};
 // SVG サムネを canvas で PNG に変換してダウンロード（ブラウザ内・外部送信なし）
 document.getElementById('thumbPng').onclick=async()=>{{
   try{{
     const res=await fetch('/note/thumb.svg?product_id={_html.escape(product_id)}');
     const svgText=await res.text();
     const W=1280,H=670;
     const img=new Image();
     const blob=new Blob([svgText],{{type:'image/svg+xml;charset=utf-8'}});
     const url=URL.createObjectURL(blob);
     img.onload=()=>{{
       const cv=document.createElement('canvas');cv.width=W;cv.height=H;
       const ctx=cv.getContext('2d');ctx.drawImage(img,0,0,W,H);
       URL.revokeObjectURL(url);
       cv.toBlob(b=>{{
         const a=document.createElement('a');a.href=URL.createObjectURL(b);
         a.download='note_thumb_{_html.escape(product_id)}.png';
         document.body.appendChild(a);a.click();a.remove();
         msg('PNGを保存しました。noteのヘッダ画像に設定してください。');
       }},'image/png');
     }};
     img.onerror=()=>msg('サムネ変換に失敗しました。');
     img.src=url;
   }}catch(e){{msg('サムネ保存に失敗: '+e.message);}}
 }};
</script></body></html>"""


class _Handler(BaseHTTPRequestHandler):
    company: Company = None  # type: ignore[assignment]
    server_version = "CompanyGUI/0.1"

    def log_message(self, *a):  # 静かに
        pass

    def handle_one_request(self):  # ブラウザ切断の無害な例外を握りつぶす
        try:
            super().handle_one_request()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            self.close_connection = True

    # ---- helpers ----------------------------------------------------------

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            # ブラウザが通信を打ち切っただけ（例: ダッシュボード再読込）。無視。
            self.close_connection = True

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    MAX_BODY = 1_048_576  # 1MB 上限（メモリ濫用の防止）

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length", 0) or 0)
        if not n:
            return {}
        if n > self.MAX_BODY:
            raise ValueError("リクエストボディが大きすぎます")
        try:
            return json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return {}

    # ---- GET --------------------------------------------------------------

    def do_GET(self):
        u = urlparse(self.path)
        c = self.company
        try:
            if u.path == "/":
                self._send(200, _INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
            elif u.path == "/dashboard":
                self._send(200, dashboard.render(c).encode("utf-8"),
                           "text/html; charset=utf-8")
            elif u.path == "/architecture":
                from . import architecture
                self._send(200, architecture.page().encode("utf-8"),
                           "text/html; charset=utf-8")
            elif u.path == "/api/arch":
                from . import architecture
                self._json(architecture.state(c))
            elif u.path == "/note/preview":
                q = parse_qs(u.query)
                pid = (q.get("product_id") or [""])[0]
                self._send(200, _note_preview_page(c, pid).encode("utf-8"),
                           "text/html; charset=utf-8")
            elif u.path == "/social/preview":
                q = parse_qs(u.query)
                sid = (q.get("id") or [""])[0]
                self._send(200, _social_preview_page(c, sid).encode("utf-8"),
                           "text/html; charset=utf-8")
            elif u.path == "/note/thumb.svg":
                from . import thumbnail
                q = parse_qs(u.query)
                pid = (q.get("product_id") or [""])[0]
                prod = c.storage.get("products", pid) or {}
                self._send(200, thumbnail.svg(prod).encode("utf-8"),
                           "image/svg+xml; charset=utf-8")
            elif u.path == "/api/state":
                self._json(_state(c))
            elif u.path == "/api/report":
                q = parse_qs(u.query)
                self._json(c.report((q.get("period") or [None])[0]))
            elif u.path == "/api/memory":
                q = parse_qs(u.query)
                text = (q.get("query") or [None])[0]
                kind = (q.get("kind") or [None])[0]
                self._json(c.memory.query(text=text, kind=kind) if (text or kind)
                           else c.memory.recent(30))
            elif u.path == "/api/skill/versions":
                q = parse_qs(u.query)
                self._json(c.skills_lab.versions((q.get("key") or [""])[0]))
            elif u.path == "/api/article":
                q = parse_qs(u.query)
                pid = (q.get("product_id") or [""])[0]
                art = c.article_for(pid)
                if art and art.get("body_markdown"):
                    from .note_channel import renumber_ordered_lists
                    art = {**art,
                           "body_markdown": renumber_ordered_lists(art["body_markdown"])}
                self._json({"article": art})
            elif u.path == "/api/logs":
                self._json(_logs(c))
            elif u.path == "/api/debug":
                self._json(_debug(c))
            else:
                self._json({"error": "not found"}, 404)
        except Exception as exc:  # noqa: BLE001
            self._json({"error": str(exc)}, 500)

    # ---- POST -------------------------------------------------------------

    def _csrf_ok(self) -> bool:
        """CSRF 対策: ブラウザからのクロスサイト POST を弾く。

        Origin が付いていれば、そのホストがループバックまたは待ち受けホストの
        場合のみ許可する。curl 等（Origin 無し）は許可（ローカル操作）。
        """
        origin = self.headers.get("Origin")
        if not origin:
            return True
        try:
            host = urlparse(origin).hostname or ""
        except ValueError:
            return False
        allowed = {"127.0.0.1", "localhost", "::1", self.server.server_address[0]}
        return host in allowed

    def do_POST(self):
        u = urlparse(self.path)
        c = self.company
        if not self._csrf_ok():
            return self._json({"error": "クロスオリジンの操作は拒否されました"}, 403)
        try:
            b = self._body()
            if u.path == "/api/plan":
                if b.get("llm"):
                    enabled = c.enable_llm()
                    if not enabled:
                        return self._json({"error": "claude CLI 未検出。雛形で継続してください。"}, 400)
                else:
                    c.disable_llm()  # チェックOFFなら雛形に戻す（切替を対称に）
                res = c.plan_products(int(b.get("n", 5)))
                self._json({"planned": res})
            elif u.path == "/api/rewrite":
                if b.get("llm"):
                    if not c.enable_llm():
                        return self._json(
                            {"error": "claude CLI 未検出。実LLM生成が使えません。"}, 400)
                else:
                    c.disable_llm()
                self._json(c.request_rewrite(b["product_id"], b.get("feedback", "")))
            elif u.path == "/api/llm/check":
                self._json(c.llm_health())
            elif u.path == "/api/llm/login":
                self._json(c.start_login())
            elif u.path == "/api/product/delete":
                if not b.get("confirm"):
                    return self._json({"error": "confirm が必要です"}, 400)
                self._json(c.delete_product(b["product_id"]))
            elif u.path == "/api/improve/system":
                if b.get("llm"):
                    c.enable_llm()
                self._json(c.propose_system_improvements(use_llm=bool(b.get("llm"))))
            elif u.path == "/api/improve/status":
                self._json(c.set_improvement_status(b["id"], b["status"]))
            elif u.path == "/api/reset":
                if b.get("confirm") != "DELETE":
                    return self._json({"error": "confirm=DELETE が必要です"}, 400)
                self._json(c.reset_data())
            elif u.path == "/api/approve":
                self._json(c.approvals.approve(b["approval_id"]).to_dict())
            elif u.path == "/api/reject":
                self._json(c.human_reject_publish(b["approval_id"], note=b.get("note", "")))
            elif u.path == "/api/publish":
                p = c.publish(b["product_id"], b["url"], b["approval_id"])
                self._json(p.to_dict())
            elif u.path == "/api/metrics":
                p = c.record_metrics(
                    b["product_id"], pv=int(b.get("pv", 0)),
                    purchases=int(b.get("purchases", 0)),
                    revenue_jpy=int(b.get("revenue", 0)), likes=int(b.get("likes", 0)),
                    rating=b.get("rating"))
                self._json(p.to_dict())
            elif u.path == "/api/evaluate":
                self._json(c.evaluate())
            elif u.path == "/api/demo":
                from .seed import seed_demo, DemoRunner
                c.tasks.runner = DemoRunner()
                self._json(seed_demo(c)["summary"])
            elif u.path == "/api/skill/propose":
                self._json(c.skills_lab.propose(
                    b["key"], purpose=b.get("purpose"), success=b.get("success"),
                    guidance=b.get("guidance"),
                    forbidden=b.get("forbidden") or None))
            elif u.path == "/api/skill/evaluate":
                self._json(c.skills_lab.evaluate(b["key"], int(b["version"])))
            elif u.path == "/api/skill/request-adoption":
                self._json(c.skills_lab.request_adoption(b["key"], int(b["version"])))
            elif u.path == "/api/skill/adopt":
                self._json(c.skills_lab.adopt(b["key"], int(b["version"]), b["approval_id"]))
            elif u.path == "/api/note/export":
                self._json(c.note_export.export(b["product_id"]))
            elif u.path == "/api/note/import":
                self._json(c.note_import.import_csv(b.get("csv", ""),
                                                    dry_run=bool(b.get("dry_run"))))
            elif u.path == "/api/config":
                self._json(c.update_config(b or {}))
            elif u.path == "/api/social/draft":
                self._json(c.social.draft(b["channel"], b["product_id"]))
            elif u.path == "/api/social/posted":
                self._json(c.social.mark_posted(b["social_id"], b["url"]).to_dict())
            elif u.path == "/api/schedule/master":
                self._json(c.scheduler.set_enabled(bool(b.get("enabled"))))
            elif u.path == "/api/schedule/job":
                self._json(c.scheduler.set_job(
                    b["name"], enabled=b.get("enabled"),
                    interval_min=b.get("interval_min")))
            elif u.path == "/api/schedule/run":
                self._json(c.scheduler.run_job(b["name"]))
            else:
                self._json({"error": "not found"}, 404)
        except PermissionError_ as exc:
            self._json({"error": str(exc)}, 403)
        except KeyError as exc:
            self._json({"error": f"missing/invalid: {exc}"}, 400)
        except Exception as exc:  # noqa: BLE001
            self._json({"error": str(exc)}, 500)


def serve(company: Company, *, host: str = "127.0.0.1", port: int = 8787,
          llm: bool = False) -> None:
    if llm:
        ok = company.enable_llm()
        print("実 LLM:", "有効 (Claude Code CLI)" if ok else "無効 (claude 未検出) → 雛形")
    if host not in ("127.0.0.1", "localhost", "::1"):
        print(f"⚠ 警告: {host} で待ち受けます。GUI に認証はありません。"
              " ローカル専用ツールなので 127.0.0.1 での利用を推奨します。")
    _Handler.company = company
    # 永続化された設定でスケジューラが有効なら起動（既定は無効なので起動しない）。
    if company.scheduler.get_state()["enabled"]:
        company.scheduler.start()
        print("定期スケジューラ: 有効（保存済み設定）")
    httpd = ThreadingHTTPServer((host, port), _Handler)
    print(f"AI会社 GUI 起動: http://{host}:{port}/  (Ctrl+C で停止)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n停止しました。")
    finally:
        company.scheduler.stop()
        httpd.server_close()


# --- 単一ページ・コックピット（外部依存なし） ---------------------------
_INDEX_HTML = r"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI会社 コックピット</title>
<style>
:root{color-scheme:light dark;--bg:#0b0e14;--panel:#151b2b;--line:#232838;--fg:#e6e9ef;
--muted:#8b97b0;--accent:#4f8cff;--good:#3fbf7f;--warn:#e0b341;--bad:#e06666}
*{box-sizing:border-box}body{font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
margin:0;background:var(--bg);color:var(--fg);line-height:1.55}
header{padding:16px 22px;border-bottom:1px solid var(--line);background:#111624;
display:flex;align-items:center;gap:14px;flex-wrap:wrap}
h1{font-size:17px;margin:0} h2{font-size:14px;color:#9fb4d8;margin:22px 0 8px}
main{padding:16px 22px 60px;max-width:1080px}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px}
.card .k{font-size:12px;color:var(--muted)} .card .v{font-size:20px;font-weight:650;margin-top:4px}
button{background:var(--accent);color:#fff;border:0;border-radius:8px;padding:7px 12px;
font-size:13px;cursor:pointer} button.ghost{background:#1e2a44;color:#cfe0ff}
button.good{background:var(--good)} button.bad{background:var(--bad)} button:disabled{opacity:.5;cursor:wait}
input,select{background:#0f1422;color:var(--fg);border:1px solid var(--line);border-radius:7px;
padding:6px 8px;font-size:13px}
table{width:100%;border-collapse:collapse;font-size:13px;background:var(--panel);
border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:middle}
th{background:#1a2133;color:#9fb4d8} .pill{padding:1px 8px;border-radius:999px;font-size:11px;background:#1e2a44}
.pill.await{background:#3a2f10;color:var(--warn)} .pill.pub{background:#123524;color:var(--good)}
.muted{color:var(--muted)} .overflow{overflow-x:auto}
#toast{position:fixed;right:16px;bottom:16px;background:#1a2133;border:1px solid var(--line);
padding:10px 14px;border-radius:8px;max-width:380px;display:none;font-size:13px;white-space:pre-wrap}
details{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin-top:8px}
summary{cursor:pointer;color:#9fb4d8}
iframe{width:100%;height:520px;border:1px solid var(--line);border-radius:10px;background:#fff}
/* 右側の空きスペースに常駐するデバッグ履歴パネル */
.dbg{position:fixed;top:72px;right:14px;width:300px;max-height:calc(100vh - 90px);
  flex-direction:column;background:var(--panel);border:1px solid var(--line);
  border-radius:12px;box-shadow:0 24px 60px -24px rgba(0,0,0,.75);z-index:50;
  overflow:hidden;display:none}
body.show-dbg .dbg{display:flex}
.dbg .dbgh{display:flex;align-items:center;gap:8px;padding:9px 11px;border-bottom:1px solid var(--line);
  background:#111624}
.dbg .dbgh b{font-size:13px} .dbg .dbgh .sp{margin-left:auto;display:flex;gap:6px}
.dbg .dbgh button{padding:4px 9px;font-size:12px}
.dbgmeta{padding:8px 11px;border-bottom:1px solid var(--line);font-size:12px}
.dbgrow{display:flex;justify-content:space-between;gap:8px;padding:1px 0;color:var(--muted)}
.dbgrow b{color:var(--fg);font-weight:600} .dbgrow b.e{color:var(--bad)}
.dbglist{overflow-y:auto;padding:6px 8px}
.di{border-left:3px solid var(--line);background:#0f1422;border-radius:6px;padding:6px 9px;margin:6px 0}
.di.error{border-left-color:var(--bad)} .di.warn{border-left-color:var(--warn)}
.di .dik{font-size:11px;font-weight:700;color:#cfe0ff}
.di.error .dik{color:var(--bad)} .di.warn .dik{color:var(--warn)}
.di .dim{font-size:12px;color:var(--fg);margin:2px 0;word-break:break-word}
.di .dit{font-size:10px;color:var(--muted)}
.banner{display:none;margin:0;padding:11px 22px;background:#3a1d1d;border-bottom:1px solid #5a2a2a;
  color:#ffd7d7;font-size:13px;line-height:1.5}
.banner b{color:#fff} .banner.warnc{background:#3a2f10;border-bottom-color:#5a4a1f;color:#ffe9b8}
.dbghead{margin:0 0 8px;padding:7px 9px;border-radius:8px;background:#3a1d1d;border:1px solid #5a2a2a;
  color:#ffd7d7;font-size:12px;line-height:1.45}
</style></head><body>
<header>
  <h1>🏢 AI会社 コックピット</h1>
  <span class="muted" id="runner"></span>
  <span class="row" style="margin-left:auto">
    <label class="muted"><input type="checkbox" id="useLlm"> 実LLM生成</label>
    <button class="good" id="btnLlmLogin" title="claude にワンクリックでログイン（ブラウザ認証）">🔑 claudeにログイン</button>
    <button class="ghost" id="btnLlmCheck" title="claude CLI のログイン/疎通を確認">接続テスト</button>
    <input id="planN" type="number" value="5" min="1" max="20" style="width:60px">
    <button id="btnPlan">商品を企画</button>
    <button class="ghost" id="btnDemo">デモ投入</button>
    <button class="ghost" id="btnEval">評価</button>
    <button class="ghost" id="btnRefresh">更新</button>
    <button class="ghost" id="btnDbg" title="デバッグ履歴の表示/非表示">🐞 デバッグ</button>
    <button class="bad" id="btnReset">データ初期化</button>
  </span>
</header>
<aside class="dbg" id="dbg">
  <div class="dbgh"><b>🐞 デバッグ履歴</b>
    <span class="sp">
      <button class="ghost" id="dbgCopy">コピー</button>
      <button class="ghost" id="dbgClose">×</button>
    </span>
  </div>
  <div class="dbgmeta" id="dbgMeta"></div>
  <div class="dbglist" id="dbgList"></div>
</aside>
<div class="banner" id="llmBanner"></div>
<main>
  <h2>経営 KPI</h2>
  <div class="grid" id="kpi"></div>

  <details open><summary>🗺 システム全体像（役割・稼働状況・データフロー）</summary>
    <iframe src="/architecture" id="arch" style="height:1180px;background:#05070d"></iframe>
  </details>

  <h2>⏳ 承認待ち（人間の判断ポイント · §21）</h2>
  <div class="overflow"><table id="pending"><thead><tr>
    <th>種別</th><th>内容</th><th>操作</th></tr></thead><tbody></tbody></table></div>

  <h2>📦 商品</h2>
  <div class="overflow"><table id="products"><thead><tr>
    <th>タイトル</th><th>カテゴリ</th><th>状態</th><th>PV</th><th>購入</th>
    <th>売上</th><th>評価</th><th>操作</th></tr></thead><tbody></tbody></table></div>

  <details open><summary>🧠 Skill 自己改善（§20）</summary>
    <div id="skills" style="margin-top:8px"></div>
    <div style="margin-top:10px" class="muted">📚 学習した教訓（差し戻しから自動獲得 → 以後の執筆に反映）:</div>
    <div id="lessons" style="margin-top:4px"></div>
  </details>

  <details open><summary>🛠 システム改修提案（売上を上げる機能提案・実装は人間が判断）</summary>
    <div class="row" style="margin-top:8px">
      <button id="btnImpGen">提案を生成</button>
      <button class="ghost" id="btnImpGenLlm">実LLMで提案</button>
      <span class="muted">KPI・実績・教訓から、売れるためのシステム改修案を起票します</span>
    </div>
    <div id="improvements" style="margin-top:8px"></div>
  </details>

  <details><summary>⚙️ 設定（チャネル有効化・運用パラメータ · §23, §36）</summary>
    <div id="settings" style="margin-top:8px"></div>
  </details>

  <details><summary>⏱️ 定期スケジュール（既定オフ · 安全な内部ジョブのみ）</summary>
    <p class="muted" style="margin:8px 0">公開・SNS投稿・承認は自動化しません。
      有効なのは 評価 / ローカルCSV取込 / SNS下書き生成 のみ（投稿は人間）。</p>
    <div class="row" style="margin-bottom:8px">
      <label><input type="checkbox" id="schedMaster"> 定期実行を有効化（マスター）</label>
      <span class="muted" id="schedRunning"></span>
    </div>
    <div id="schedJobs"></div>
  </details>

  <details><summary>📣 SNS 下書き（X / TikTok · §32-33, 投稿は人間）</summary>
    <div id="socialList" style="margin-top:8px"></div>
  </details>

  <details><summary>📤 note 連携（公開用エクスポート / 実績CSV取込 · §22, 付録A#2）</summary>
    <p class="muted" style="margin:8px 0">公開は note エディタに貼り付け（自動投稿はしない, §22）。
      売上/PV は note 管理画面の CSV をここに貼って取り込む。</p>
    <textarea id="noteCsv" placeholder="note の売上/アクセス CSV を貼り付け（タイトル,URL,ビュー,購入数,売上金額,スキ …）"
      style="width:100%;height:90px;background:#0f1422;color:var(--fg);border:1px solid var(--line);border-radius:7px;padding:8px"></textarea>
    <div class="row" style="margin-top:6px">
      <button class="ghost" id="btnImportDry">取り込み（下書き確認）</button>
      <button id="btnImport">取り込み実行</button>
    </div>
  </details>

  <details open><summary>📜 ログ / 実行履歴（AIが何をしたか）</summary>
    <div class="row" style="margin-top:8px">
      <button class="ghost" id="btnLogs">最新に更新</button>
      <span class="muted">研究→企画→執筆→レビューの各ステップと結果を新しい順に表示</span>
    </div>
    <div class="overflow"><table id="logs"><thead><tr>
      <th>時刻</th><th>担当</th><th>ステップ</th><th>状態</th><th>レビュー</th><th>メモ</th>
    </tr></thead><tbody></tbody></table></div>
  </details>

  <details><summary>🔎 レポート / メモリ</summary>
    <div class="row" style="margin-top:8px">
      <button class="ghost" id="btnReport">先月レポート</button>
      <input id="memq" placeholder="メモリ検索（例: 副業）">
      <button class="ghost" id="btnMem">検索</button>
    </div>
    <pre id="out" class="muted" style="white-space:pre-wrap;margin-top:8px"></pre>
  </details>

  <details><summary>📊 ダッシュボード（§25）</summary>
    <iframe src="/dashboard" id="dash"></iframe>
  </details>
</main>
<div id="toast"></div>
<script>
const $=s=>document.querySelector(s), tbody=s=>$(s).querySelector('tbody');
function toast(m){const t=$('#toast');t.textContent=m;t.style.display='block';
  clearTimeout(window._t);window._t=setTimeout(()=>t.style.display='none',4000);}
async function api(path,method='GET',body){
  const r=await fetch(path,{method,headers:{'Content-Type':'application/json'},
    body:body?JSON.stringify(body):undefined});
  const j=await r.json(); if(!r.ok) throw new Error(j.error||('HTTP '+r.status)); return j;}
const yen=n=>'¥'+(n||0).toLocaleString();
function esc(s){return String(s==null?'':s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}

async function refresh(){
  const s=await api('/api/state');
  $('#runner').textContent='ランナー: '+s.runner+' · 本日タスク '+s.tasks_today+'/'+s.max_tasks_per_day
    +' · 実験 '+s.progress.created+'/'+s.progress.target_products
    +(s.build?(' · 画面 build:'+s.build):'');
  const k=s.summary;
  $('#kpi').innerHTML=[
    ['総売上',yen(k.total_revenue_jpy)],['今月売上',yen(k.month_revenue_jpy)],
    ['商品数',k.product_count],['公開',k.published_count],['購入',k.purchases],
    ['PV',(k.pv||0).toLocaleString()],['購入率',(k.conversion_rate*100).toFixed(1)+'%'],
    ['AIコスト',k.ai_cost_units],['1商品コスト',k.ai_cost_per_product]
  ].map(([a,b])=>`<div class="card"><div class="k">${a}</div><div class="v">${b}</div></div>`).join('');

  tbody('#pending').innerHTML=s.pending.length? s.pending.map(a=>`<tr>
    <td><span class="pill await">${esc(a.kind)}</span></td><td>${esc(a.summary)}</td>
    <td class="row">
      <button class="good" onclick="approve('${a.id}')">承認</button>
      <button class="bad" onclick="reject('${a.id}')">却下</button>
    </td></tr>`).join('') : '<tr><td colspan=3 class="muted">なし</td></tr>';

  tbody('#products').innerHTML=s.products.length? s.products.map(p=>{
    const st = p.status==='awaiting_approval'?'<span class="pill await">公開待ち</span>'
      : p.status==='published'?'<span class="pill pub">公開</span>'
      : p.status==='review'?'<span class="pill">差し戻し中</span>'+(p.pending_feedback?' <span class="muted">📝指示あり</span>':'')
      :`<span class="pill">${esc(p.status)}</span>`;
    let act=`<button class="ghost" onclick="viewArticle('${p.id}')">記事を読む</button> `;
    act+=`<button class="bad" onclick="deleteProduct('${p.id}','${(p.title||'').replace(/'/g,'')}')">削除</button> `;
    // 修正依頼（差し戻し中/公開待ちの記事を書き直す, §4）
    if(p.status==='review'||p.status==='awaiting_approval')
      act+=`<button class="ghost" onclick="requestRewrite('${p.id}')">修正依頼</button> `;
    if(p.status==='awaiting_approval'){
      if(p.approval_status==='approved')
        act+=`<button class="good" onclick="recordUrl('${p.id}','${p.approval_id}')">公開URL記録</button> `;
      else if(p.approval_id)
        act+=`<button class="good" onclick="approve('${p.approval_id}')">承認</button>`
            +` <button class="bad" onclick="reject('${p.approval_id}')">却下</button> `;
    }
    if(p.status==='published')
      act+=`<button class="ghost" onclick="metrics('${p.id}')">実績入力</button> `;
    if(p.status==='published'||p.status==='awaiting_approval')
      act+=`<button class="ghost" onclick="notePreview('${p.id}')">note貼付(書式)</button>`
           +` <button class="ghost" onclick="noteExport('${p.id}')">MD出力</button> `;
    if(p.status==='published'&&p.url)
      act+=`<a href="${esc(p.url)}" target="_blank" class="muted">公開URL↗</a> `;
    if(p.status==='published'||p.status==='awaiting_approval')
      act+=`<button class="ghost" onclick="social('x','${p.id}')">X下書き</button>`
           +` <button class="ghost" onclick="social('tiktok','${p.id}')">TikTok下書き</button>`;
    return `<tr><td>${esc(p.title)}</td><td>${esc(p.category)}</td><td>${st}</td>
      <td>${p.pv}</td><td>${p.purchases}</td><td>${yen(p.revenue_jpy)}</td>
      <td>${p.outcome?esc(p.outcome):'-'}</td><td class="row">${act}</td></tr>`;
  }).join('') : '<tr><td colspan=8 class="muted">まだ商品がありません。「商品を企画」から。</td></tr>';

  $('#skills').innerHTML='<div class="overflow"><table><thead><tr><th>Skill</th><th>現行版</th>'
    +'<th>改善案</th><th>操作</th></tr></thead><tbody>'
    + s.skills.map(sk=>`<tr><td>${esc(sk.key)}</td><td>v${sk.version}</td>
        <td>${sk.candidates}</td><td class="row">
        <button class="ghost" onclick="propose('${sk.key}')">改善案</button>
        <button class="ghost" onclick="showVersions('${sk.key}')">履歴</button></td></tr>`).join('')
    +'</tbody></table></div>';
  renderImprovements(s.improvements||[]);
  $('#lessons').innerHTML=(s.lessons&&s.lessons.length)
    ? s.lessons.map(l=>`<div class="muted" style="padding:3px 0">
        ✅ <b>${esc(l.skill)}</b>: ${esc(l.guideline)} <span style="opacity:.6">(${l.count}回)</span></div>`).join('')
    : '<div class="muted">まだ教訓はありません（差し戻しが繰り返されると自動で獲得します）。</div>';
  renderSettings(s.config); renderSchedule(s.schedule); renderSocial(s.social);
  loadLogs(); loadDebug();
  $('#dash').src='/dashboard?'+Date.now();
}

async function loadDebug(){try{const d=await api('/api/debug');
  window.__dbgText=d.text||'';
  const c=d.counts||{};
  const head=d.headline?`<div class="dbghead">${esc(d.headline)}</div>`:'';
  // 履歴に未ログイン等の診断があり、かつ実LLM ON のときは上部バナーも自動表示。
  if(d.headline && $('#useLlm').checked && !window.__llmChecked) setLlmBanner({reason:'headline',detail:d.headline});
  $('#dbgMeta').innerHTML= head+
     `<div class="dbgrow"><span>ランナー</span><b>${esc(d.runner||'')}</b></div>`
    +`<div class="dbgrow"><span>本日タスク / 承認待ち</span><b>${c.tasks_today||0} / ${c.pending_approvals||0}</b></div>`
    +`<div class="dbgrow"><span>公開待ち / 差戻 / 公開</span><b>${c.await||0} / ${c.review||0} / ${c.published||0}</b></div>`
    +`<div class="dbgrow"><span>エラー / 警告</span><b class="${c.errors?'e':''}">${c.errors||0} / ${c.warns||0}</b></div>`;
  const its=d.issues||[];
  $('#dbgList').innerHTML=its.length? its.map(i=>`<div class="di ${esc(i.sev)}">
      <div class="dik">${esc(i.kind)}</div>
      <div class="dim">${esc(i.msg)}</div>
      ${i.ts?`<div class="dit">${esc(i.ts)}</div>`:''}</div>`).join('')
    : '<div class="muted" style="padding:10px 6px">問題は検出されていません 🟢</div>';
  }catch(e){/* デバッグ取得失敗は致命的でないので無視 */}}

const IMP_BADGE={new:'🆕 新規',accepted:'✅ 採用',done:'🏁 完了',rejected:'🗑 却下'};
function renderImprovements(list){
  if(!list.length){$('#improvements').innerHTML='<div class="muted">まだ提案はありません。「提案を生成」を押してください。</div>';return;}
  $('#improvements').innerHTML=list.map(im=>`<div style="border:1px solid var(--line);border-radius:9px;padding:10px;margin-bottom:8px">
    <div class="row" style="justify-content:space-between">
      <b>${esc(im.title)}</b>
      <span class="muted">${IMP_BADGE[im.status]||im.status} ・ ${esc(im.category||'')} ・ 規模${esc(im.effort||'')} ・ ${im.source==='llm'?'AI':'自動'}</span>
    </div>
    <div class="muted" style="margin-top:4px">課題: ${esc(im.problem||'')}</div>
    <div class="muted">仮説: ${esc(im.hypothesis||'')}</div>
    <div class="muted">期待効果: ${esc(im.expected_effect||'')}</div>
    <div class="row" style="margin-top:6px">
      <button class="good" onclick="impStatus('${im.id}','accepted')">採用</button>
      <button class="ghost" onclick="impStatus('${im.id}','done')">完了</button>
      <button class="bad" onclick="impStatus('${im.id}','rejected')">却下</button>
    </div></div>`).join('');
}
async function impStatus(id,status){try{await api('/api/improve/status','POST',{id,status});
  toast('提案を'+status+'にしました');refresh();}catch(e){toast('エラー: '+e.message);}}
async function loadLogs(){try{const r=await api('/api/logs');
  const badge=v=>v==='pass'?'<span class="pill pub">pass</span>'
    :v==='reject'?'<span class="pill await">reject</span>':(v?esc(v):'-');
  tbody('#logs').innerHTML=(r.tasks||[]).length? r.tasks.map(t=>`<tr>
    <td class="muted">${esc((t.ts||'').replace('T',' ').slice(0,19))}</td>
    <td>${esc(t.agent)}</td><td>${esc(t.step)}</td>
    <td>${esc(t.status)}</td><td>${badge(t.review)}</td>
    <td class="muted">${esc(t.notes)}</td></tr>`).join('')
    : '<tr><td colspan=6 class="muted">まだ実行ログがありません。「商品を企画」から。</td></tr>';
  }catch(e){/* ログ取得失敗は致命的でないので無視 */}}

const CFG_LABELS={initial_price_jpy:'初期価格(円)',max_tasks_per_day:'1日タスク上限(0=無制限)',
  max_publishes_per_day:'1日公開上限',max_rewrites:'自動再執筆 上限',
  target_conversion_rate:'目標購入率',similarity_threshold:'重複ガード閾値(0-1)',
  breakeven_product_count:'損益分岐 商品数',
  retreat_zero_purchase_rounds:'撤退ラウンド',x_enabled:'X チャネル有効',tiktok_enabled:'TikTok チャネル有効'};
function renderSettings(cfg){
  const rows=Object.keys(cfg).map(k=>{
    const v=cfg[k];
    if(typeof v==='boolean')
      return `<label class="row" style="gap:6px"><input type="checkbox" data-cfg="${k}" ${v?'checked':''}> ${CFG_LABELS[k]||k}</label>`;
    return `<label class="row" style="gap:6px">${CFG_LABELS[k]||k}
      <input type="number" step="${k==='target_conversion_rate'?'0.01':'1'}" data-cfg="${k}" value="${v}" style="width:110px"></label>`;
  }).join('');
  $('#settings').innerHTML=`<div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(240px,1fr))">${rows}</div>
    <div style="margin-top:10px"><button id="btnSaveCfg">設定を保存</button></div>`;
  $('#btnSaveCfg').onclick=async()=>{
    const ch={};document.querySelectorAll('[data-cfg]').forEach(el=>{
      ch[el.dataset.cfg]= el.type==='checkbox'?el.checked:el.value;});
    try{await api('/api/config','POST',ch);toast('設定を保存しました');refresh();}catch(e){toast(e.message);}
  };
}
function renderSchedule(sc){
  $('#schedMaster').checked=!!sc.enabled;
  $('#schedRunning').textContent=sc.enabled?(sc.running?'稼働中':'待機'):'無効';
  const names={evaluate:'評価の定期実行',note_import:'note CSV 取込 (data/inbox/note.csv)',
    social_draft:'SNS 下書き生成'};
  $('#schedJobs').innerHTML='<div class="overflow"><table><thead><tr><th>ジョブ</th><th>有効</th>'
    +'<th>間隔(分)</th><th>最終実行</th><th></th></tr></thead><tbody>'
    +Object.entries(sc.jobs).map(([k,j])=>`<tr>
      <td>${names[k]||k}</td>
      <td><input type="checkbox" ${j.enabled?'checked':''} onchange="setJob('${k}',{enabled:this.checked})"></td>
      <td><input type="number" min="1" value="${j.interval_min}" style="width:90px"
          onchange="setJob('${k}',{interval_min:+this.value})"></td>
      <td class="muted">${j.last_run?esc(j.last_run.slice(0,16)):'-'}</td>
      <td><button class="ghost" onclick="runJob('${k}')">今すぐ</button></td></tr>`).join('')
    +'</tbody></table></div>';
}
function renderSocial(list){
  if(!list||!list.length){$('#socialList').innerHTML='<span class="muted">下書きはまだありません。商品行の「X下書き / TikTok下書き」から。</span>';return;}
  $('#socialList').innerHTML='<div class="overflow"><table><thead><tr><th>チャネル</th><th>状態</th>'
    +'<th>操作</th></tr></thead><tbody>'
    +list.map(p=>`<tr><td>${esc(p.channel)}</td>
      <td><span class="pill${p.status==='posted'?' pub':''}">${esc(p.status)}</span></td>
      <td class="row"><button class="ghost" onclick="socialPreview('${p.id}')">試し読み</button>
      ${p.status!=='posted'?`<button class="ghost" onclick="socialPosted('${p.id}')">投稿URL記録</button>`:esc(p.url||'')}</td></tr>`).join('')
    +'</tbody></table></div>';
}
async function setJob(name,patch){try{await api('/api/schedule/job','POST',{name,...patch});
  toast('スケジュール更新');refresh();}catch(e){toast(e.message);}}
async function runJob(name){try{const r=await api('/api/schedule/run','POST',{name});
  $('#out').textContent=JSON.stringify(r,null,2);toast('実行: '+name+(r.ok?' OK':' 失敗'));refresh();}catch(e){toast(e.message);}}
async function social(channel,pid){try{const r=await api('/api/social/draft','POST',{channel,product_id:pid});
  toast(channel+' 下書きを作成。試し読みを開きます（投稿は人間）。');refresh();
  if(r.social_id) socialPreview(r.social_id);}catch(e){toast(e.message);}}
function socialPreview(id){window.open('/social/preview?id='+encodeURIComponent(id),'_blank');}
async function socialPosted(id){const url=prompt('投稿した X/TikTok の URL を入力（人間確認の承認が前提）:');
  if(!url)return; try{await api('/api/social/posted','POST',{social_id:id,url});
  toast('投稿を記録しました');refresh();}catch(e){toast('エラー: '+e.message+'（先に承認待ちで承認が必要です）');}}
async function approve(id){try{await api('/api/approve','POST',{approval_id:id});
  toast('承認しました。noteに貼って公開したら「公開URL記録」を押してください。');refresh();}
  catch(e){toast('エラー: '+e.message);}}
async function recordUrl(pid,aid){const url=prompt('公開した note の URL を入力:');
  if(!url)return; try{await api('/api/publish','POST',{product_id:pid,url,approval_id:aid});
  toast('公開URLを記録しました');refresh();}catch(e){toast('エラー: '+e.message);}}
async function deleteProduct(pid,title){
  if(!confirm('この商品と記事を削除します：\\n'+(title||pid)+'\\nよろしいですか？'))return;
  try{const r=await api('/api/product/delete','POST',{product_id:pid,confirm:true});
  toast('削除しました（記事'+r.removed_articles+'件）');refresh();}
  catch(e){toast('エラー: '+e.message);}}
async function requestRewrite(pid){
  let def='';try{const s=await api('/api/state');const p=s.products.find(x=>x.id===pid);def=(p&&p.pending_feedback)||'';}catch(e){}
  const fb=prompt('修正依頼の内容（差し戻しコメントがあれば初期表示。例: 具体例を数値つきで3件）:', def);
  if(fb==null||!fb.trim())return;
  toast('修正を依頼中…（実LLMだと数分かかります）');
  try{const r=await api('/api/rewrite','POST',{product_id:pid,feedback:fb,llm:$('#useLlm').checked});
  if(r.llm===false){
    const why=r.llm_error?('（原因: '+r.llm_error+'）'):'';
    toast('⚠ LLMがフォールバック'+why+'。ループが1回で停止します。左上「実LLM生成」ON・claudeログイン・設定でタスク上限0 を確認してください。');
  } else toast(`修正依頼: ${r.rounds||1}回改稿。`+(r.passed?'レビュー通過→承認待ちへ。':'まだ差し戻し。指摘を足して再依頼できます。'));
  refresh();}catch(e){toast('エラー: '+e.message);}}
async function reject(id){const note=prompt('却下理由（ライターへの差し戻し指示になります）:')||'';
  try{await api('/api/reject','POST',{approval_id:id,note});
  toast('差し戻しました。'+(note?'この指示は「修正依頼」で反映されます。':'')+'商品はreviewに戻りました。');
  refresh();}catch(e){toast('エラー: '+e.message);}}
async function metrics(pid){const pv=+prompt('PV',0),pu=+prompt('購入数',0),rev=+prompt('売上(円)',0);
  try{await api('/api/metrics','POST',{product_id:pid,pv,purchases:pu,revenue:rev});
  toast('実績を記録しました');refresh();}catch(e){toast('エラー: '+e.message);}}
async function propose(key){const guidance=prompt('改善したい手順・ガイダンス（v+1 として保存されます）');
  if(guidance==null)return; try{const v=await api('/api/skill/propose','POST',{key,guidance});
  await api('/api/skill/evaluate','POST',{key,version:v.version});
  const apr=await api('/api/skill/request-adoption','POST',{key,version:v.version});
  toast('改善案 v'+v.version+' を提案。承認待ちに追加（Skill採用）。');refresh();}
  catch(e){toast('エラー: '+e.message);}}
async function showVersions(key){const vs=await api('/api/skill/versions?key='+encodeURIComponent(key));
  $('#out').textContent=JSON.stringify(vs,null,2);toast('履歴を下部に表示');}
async function viewArticle(pid){try{const r=await api('/api/article?product_id='+encodeURIComponent(pid));
  const a=r.article;
  if(!a){$('#out').textContent='(この商品の記事はまだ生成されていません)';toast('記事なし');return;}
  const body=a.body_markdown||a.body||'(本文フィールドが見つかりません)';
  let head='';
  if(a.is_skeleton){head='⚠ これは雛形（自動生成のたたき台）です。\n'
    +'実LLM生成をONにすると本物の記事になり、レビュー通過後に「承認待ち」へ進みます。\n'
    +'（左上の「実LLM生成」にチェック → 商品を企画。※ claude CLI ログインが必要）\n\n'
    +'─────────────────────────────\n\n';}
  $('#out').textContent=head+body;
  toast(a.is_skeleton?'雛形を下部に表示（実LLM生成OFF）':'記事本文を下部に表示');
  }catch(e){toast('エラー: '+e.message);}}
function notePreview(pid){window.open('/note/preview?product_id='+encodeURIComponent(pid),'_blank');}
async function noteExport(pid){try{const r=await api('/api/note/export','POST',{product_id:pid});
  $('#out').textContent=r.markdown;
  try{await navigator.clipboard.writeText(r.markdown);toast('note本文をコピー＋書き出し: '+r.path);}
  catch(e){toast('note公開用を書き出し: '+r.path+'（下部に本文表示）');}
  }catch(e){toast('エラー: '+e.message);}}
async function noteImport(dry){try{const csv=$('#noteCsv').value;
  const r=await api('/api/note/import','POST',{csv,dry_run:dry});
  $('#out').textContent=JSON.stringify(r,null,2);
  toast((dry?'下書き: ':'取込: ')+'一致 '+r.matched+' 件 / 未一致 '+(r.unmatched||[]).length+' 件');
  if(!dry) refresh();}catch(e){toast('エラー: '+e.message);}}

$('#btnPlan').onclick=async()=>{const b=$('#btnPlan');b.disabled=true;b.textContent='実行中…';
  try{const r=await api('/api/plan','POST',{n:+$('#planN').value,llm:$('#useLlm').checked});
  const pl=r.planned||[]; const err=pl.filter(x=>x.status==='error');
  const ok=pl.length-err.length;
  if(err.length){$('#out').textContent='失敗:\\n'+err.map(e=>'・'+e.theme+': '+e.error).join('\\n');
    toast(`企画 ${ok}/${pl.length} 件成功。${err.length}件失敗（下部に理由）。上限なら設定でタスク上限を0に。`);}
  else toast(`企画 ${ok} 件を実行しました`);
  refresh();}catch(e){toast('エラー: '+e.message);}
  finally{b.disabled=false;b.textContent='商品を企画';}};
$('#btnDemo').onclick=async()=>{if(!confirm('架空デモデータを投入します。よろしいですか？'))return;
  try{await api('/api/demo','POST',{});toast('デモ投入完了');refresh();}catch(e){toast(e.message);}};
$('#btnEval').onclick=async()=>{try{const r=await api('/api/evaluate','POST',{});
  $('#out').textContent=JSON.stringify(r.actions,null,2);toast('評価しました');refresh();}catch(e){toast(e.message);}};
$('#btnRefresh').onclick=refresh;
$('#btnLogs').onclick=loadLogs;
$('#btnImpGen').onclick=async()=>{try{const r=await api('/api/improve/system','POST',{});
  toast('改修提案を生成: 新規'+r.added+'件 / 合計'+r.total+'件');refresh();}catch(e){toast('エラー: '+e.message);}};
$('#btnImpGenLlm').onclick=async()=>{const b=$('#btnImpGenLlm');b.disabled=true;b.textContent='生成中…';
  try{const r=await api('/api/improve/system','POST',{llm:true});
  toast('実LLMで改修提案を生成: 新規'+r.added+'件');refresh();}catch(e){toast('エラー: '+e.message);}
  finally{b.disabled=false;b.textContent='実LLMで提案';}};
$('#btnReset').onclick=async()=>{
  if(!confirm('全データ（商品・記事・タスク・承認・実績など）を削除して初期化します。\\n実行前に自動で data のバックアップ(zip)を作成します。よろしいですか？'))return;
  if(prompt('確認のため DELETE と入力してください:')!=='DELETE'){toast('中止しました');return;}
  try{const r=await api('/api/reset','POST',{confirm:'DELETE'});
  toast('初期化しました'+(r.backup?'（バックアップ: '+r.backup+'）':''));refresh();}
  catch(e){toast('エラー: '+e.message);}};
$('#btnImport').onclick=()=>noteImport(false);
$('#btnImportDry').onclick=()=>noteImport(true);
$('#schedMaster').onchange=async(e)=>{try{await api('/api/schedule/master','POST',{enabled:e.target.checked});
  toast('定期実行: '+(e.target.checked?'有効':'無効'));refresh();}catch(err){toast(err.message);}};
$('#btnReport').onclick=async()=>{const r=await api('/api/report');$('#out').textContent=JSON.stringify(r,null,2);};
$('#btnMem').onclick=async()=>{const r=await api('/api/memory?query='+encodeURIComponent($('#memq').value));
  $('#out').textContent=JSON.stringify(r,null,2);};
// 実LLM の疎通/ログイン確認バナー。
function setLlmBanner(r){const el=$('#llmBanner');
  if(!r){el.style.display='none';return;}
  let msg, warn=false;
  if(r.reason==='not_logged_in')
    msg='claude CLI が<b>未ログイン</b>です。右のボタンでワンクリックログイン（ブラウザ認証）できます。ログインするまで生成はすべて雛形にフォールバックします。'
        +' <button class="good" style="margin-left:8px" onclick="llmLogin()">🔑 claudeにログイン</button>';
  else if(r.reason==='no_binary')
    msg='claude CLI が<b>見つかりません</b>。インストールと PATH を確認してください。';
  else if(r.reason==='timeout'){msg='claude CLI の応答がありません（タイムアウト/起動失敗）。'; }
  else if(r.reason==='headline'){msg=esc(r.detail||''); warn=true;}
  else msg='claude CLI エラー: '+esc(r.detail||'');
  el.innerHTML='⚠ '+msg;
  el.className='banner'+(warn?' warnc':''); el.style.display='block';}
async function llmCheck(silent){try{
  if(!silent) toast('claude CLI の疎通を確認中…（数秒かかります）');
  const r=await api('/api/llm/check','POST',{}); window.__llmChecked=true;
  if(r.ok){setLlmBanner(null);toast('実LLM 疎通OK。ログイン済みです。');}
  else setLlmBanner(r);
  return r;}catch(e){if(!silent)toast('確認に失敗: '+e.message);}}
// claude ワンクリックログイン：ローカル端末で公式ログインを起動 → 完了を自動検知。
async function llmLogin(){try{
  const r=await api('/api/llm/login','POST',{});
  if(!r.launched){setLlmBanner({reason:r.reason||'error',detail:r.detail});
    toast('ログイン起動に失敗: '+(r.detail||''));return;}
  toast('ログイン用ターミナルを起動しました。ブラウザで認証を完了してください。完了を自動確認します…');
  const el=$('#llmBanner'); el.className='banner warnc';
  el.innerHTML='⏳ ブラウザで claude ログインを完了してください（このウィンドウはそのままでOK。完了を数秒ごとに自動確認します）。';
  el.style.display='block';
  let n=0; clearInterval(window.__loginPoll);
  window.__loginPoll=setInterval(async()=>{ n++;
    const s=await llmCheck(true);
    if(s&&s.ok){clearInterval(window.__loginPoll);setLlmBanner(null);
      $('#useLlm').checked=true; window.__llmChecked=true;
      toast('✅ ログイン完了。実LLM生成が使えます。');loadDebug();}
    else if(n>=40){clearInterval(window.__loginPoll);
      toast('自動確認を打ち切りました。ログイン後に「接続テスト」を押してください。');}
  },3000);
}catch(e){toast('エラー: '+e.message);}}
$('#btnLlmLogin').onclick=()=>llmLogin();
$('#btnLlmCheck').onclick=()=>llmCheck(false);
$('#useLlm').onchange=(e)=>{ if(e.target.checked) llmCheck(false); else {setLlmBanner(null);window.__llmChecked=false;} };
// デバッグ履歴パネル：広い画面では既定で右側に表示。トグル/コピー/閉じる。
if(window.innerWidth>=1400) document.body.classList.add('show-dbg');
$('#btnDbg').onclick=()=>{document.body.classList.toggle('show-dbg');loadDebug();};
$('#dbgClose').onclick=()=>document.body.classList.remove('show-dbg');
$('#dbgCopy').onclick=async()=>{try{await navigator.clipboard.writeText(window.__dbgText||'');
  toast('デバッグ要約をコピーしました。そのまま貼り付けて共有できます。');}
  catch(e){toast('コピー不可（パネルのテキストを手動選択してください）');}};
setInterval(loadDebug, 8000);
refresh();
</script></body></html>"""
