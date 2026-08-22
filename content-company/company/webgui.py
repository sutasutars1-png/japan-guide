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
    } for p in products]
    prod_rows.sort(key=lambda r: (r["status"] != "awaiting_approval", r["id"]))
    social = c.social.list()
    return {
        "summary": c.kpi.summary(),
        "progress": c.experiments.progress(),
        "pending": pending,
        "products": prod_rows,
        "skills": c.skills_lab.all_current(),
        "tasks_today": c.cost.tasks_today(),
        "max_tasks_per_day": c.config.max_tasks_per_day,
        "runner": type(c.tasks.runner).__name__,
        "config": c.config.editable_snapshot(),
        "schedule": c.scheduler.get_state(),
        "channels": {"x": c.config.x_enabled, "tiktok": c.config.tiktok_enabled},
        "social": social,
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
<div class="muted" style="margin-top:10px">価格: {price}円 ／ ハッシュタグ:</div>
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
            elif u.path == "/note/preview":
                q = parse_qs(u.query)
                pid = (q.get("product_id") or [""])[0]
                self._send(200, _note_preview_page(c, pid).encode("utf-8"),
                           "text/html; charset=utf-8")
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
                self._json(c.request_rewrite(b["product_id"], b.get("feedback", "")))
            elif u.path == "/api/product/delete":
                if not b.get("confirm"):
                    return self._json({"error": "confirm が必要です"}, 400)
                self._json(c.delete_product(b["product_id"]))
            elif u.path == "/api/reset":
                if b.get("confirm") != "DELETE":
                    return self._json({"error": "confirm=DELETE が必要です"}, 400)
                self._json(c.reset_data())
            elif u.path == "/api/approve":
                self._json(c.approvals.approve(b["approval_id"]).to_dict())
            elif u.path == "/api/reject":
                self._json(c.approvals.reject(b["approval_id"], note=b.get("note", "")).to_dict())
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
</style></head><body>
<header>
  <h1>🏢 AI会社 コックピット</h1>
  <span class="muted" id="runner"></span>
  <span class="row" style="margin-left:auto">
    <label class="muted"><input type="checkbox" id="useLlm"> 実LLM生成</label>
    <input id="planN" type="number" value="5" min="1" max="20" style="width:60px">
    <button id="btnPlan">商品を企画</button>
    <button class="ghost" id="btnDemo">デモ投入</button>
    <button class="ghost" id="btnEval">評価</button>
    <button class="ghost" id="btnRefresh">更新</button>
    <button class="bad" id="btnReset">データ初期化</button>
  </span>
</header>
<main>
  <h2>経営 KPI</h2>
  <div class="grid" id="kpi"></div>

  <h2>⏳ 承認待ち（人間の判断ポイント · §21）</h2>
  <div class="overflow"><table id="pending"><thead><tr>
    <th>種別</th><th>内容</th><th>操作</th></tr></thead><tbody></tbody></table></div>

  <h2>📦 商品</h2>
  <div class="overflow"><table id="products"><thead><tr>
    <th>タイトル</th><th>カテゴリ</th><th>状態</th><th>PV</th><th>購入</th>
    <th>売上</th><th>評価</th><th>操作</th></tr></thead><tbody></tbody></table></div>

  <details><summary>🧠 Skill 自己改善（§20）</summary>
    <div id="skills" style="margin-top:8px"></div>
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
    +' · 実験 '+s.progress.created+'/'+s.progress.target_products;
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
      : p.status==='published'?'<span class="pill pub">公開</span>':`<span class="pill">${esc(p.status)}</span>`;
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
    if(p.status==='published'){
      if(p.url) act+=`<a href="${esc(p.url)}" target="_blank" class="muted">公開URL↗</a> `;
      act+=`<button class="ghost" onclick="social('x','${p.id}')">X下書き</button>`
           +` <button class="ghost" onclick="social('tiktok','${p.id}')">TikTok下書き</button>`;
    }
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
  renderSettings(s.config); renderSchedule(s.schedule); renderSocial(s.social);
  loadLogs();
  $('#dash').src='/dashboard?'+Date.now();
}

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
      <td class="row"><button class="ghost" onclick="showSocial('${p.id}')">内容</button>
      ${p.status!=='posted'?`<button class="ghost" onclick="socialPosted('${p.id}')">投稿URL記録</button>`:esc(p.url||'')}</td></tr>`).join('')
    +'</tbody></table></div>';
}
async function setJob(name,patch){try{await api('/api/schedule/job','POST',{name,...patch});
  toast('スケジュール更新');refresh();}catch(e){toast(e.message);}}
async function runJob(name){try{const r=await api('/api/schedule/run','POST',{name});
  $('#out').textContent=JSON.stringify(r,null,2);toast('実行: '+name+(r.ok?' OK':' 失敗'));refresh();}catch(e){toast(e.message);}}
async function social(channel,pid){try{const r=await api('/api/social/draft','POST',{channel,product_id:pid});
  $('#out').textContent=JSON.stringify(r.content,null,2);
  toast(channel+' 下書きを作成。承認待ち(人間確認)に追加。下部に内容表示。');refresh();}catch(e){toast(e.message);}}
function showSocial(id){api('/api/state').then(s=>{const p=(s.social||[]).find(x=>x.id===id);
  $('#out').textContent=p?JSON.stringify(p.content,null,2):'(見つかりません)';toast('下部に内容表示');});}
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
async function requestRewrite(pid){const fb=prompt('修正依頼の内容（例: 冒頭をもっと具体的に／価格の根拠を追加）:');
  if(fb==null||!fb.trim())return;
  toast('修正を依頼中…（実LLMだと数分かかります）');
  try{const r=await api('/api/rewrite','POST',{product_id:pid,feedback:fb});
  if(r.llm===false) toast('雛形のため書き直しても骨格のままです。実LLM生成をONにしてください。');
  else toast(r.passed?'修正版がレビュー通過。承認待ちへ。':'修正版はレビューで差し戻し（reviewに戻りました）。');
  refresh();}catch(e){toast('エラー: '+e.message);}}
async function reject(id){const note=prompt('却下理由（任意）')||'';
  try{await api('/api/reject','POST',{approval_id:id,note});toast('却下しました');refresh();}
  catch(e){toast('エラー: '+e.message);}}
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
  try{await api('/api/plan','POST',{n:+$('#planN').value,llm:$('#useLlm').checked});
  toast('企画を実行しました');refresh();}catch(e){toast('エラー: '+e.message);}
  finally{b.disabled=false;b.textContent='商品を企画';}};
$('#btnDemo').onclick=async()=>{if(!confirm('架空デモデータを投入します。よろしいですか？'))return;
  try{await api('/api/demo','POST',{});toast('デモ投入完了');refresh();}catch(e){toast(e.message);}};
$('#btnEval').onclick=async()=>{try{const r=await api('/api/evaluate','POST',{});
  $('#out').textContent=JSON.stringify(r.actions,null,2);toast('評価しました');refresh();}catch(e){toast(e.message);}};
$('#btnRefresh').onclick=refresh;
$('#btnLogs').onclick=loadLogs;
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
refresh();
</script></body></html>"""
